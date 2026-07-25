# -*- coding: utf-8 -*-
"""Katman 2 · Post-pass: gerçek yükle zaman/maliyet düzeltmesi (mimari §5.4, issue #21).

MILP/greedy'nin sabit-yük (tam kapasite) varsayımıyla ürettiği zamanlama muhafazakârdır
(§5.4: "süreyi asla eksik, SLA'yı asla iyimser göstermez"). Bu modül, seçim/akış kararları
kesinleştikten SONRA, her aracın rotasını gerçekte taşıdığı desiyle yeniden zamanlar:
elleçleme süreleri kısalır (gerçek yük <= tam kapasite varsayımı), kalkış/varış anları
buna göre GERİYE (erkene) çekilir — mimari §5.4'ün "kalkışları SLA'ya göre geri çeker"
ifadesinin karşılığı budur; hiçbir zaman ileriye/geç çekilmez, yalnız düzeltilir.

Çıktı `plan_yazici.AracPlan` listesidir. Katman 3 ile kod paylaşmama kuralına (§6) uyarak
maliyet/süre formülleri burada (katman2) `katman3_simulator`'dan bağımsız, kasıtlı ikinci
kez yazılmıştır — aynı sabitlerle (config.ELLECLEME_DK_PER_DESI, SLA_CEZA_TL_PER_DESI_SAAT)
ama ayrı kod yolu, böylece iki tarafın örtüşmesi anlamlı bir doğrulama olur.

Kapsam notu: bir servis adayının birden fazla fiziksel kopyası (x[s] > 1) varsa, kopyalar
arası yük paylaşımı `_bin_pack` ile servis bazında (bacak bazında değil) tek seferde
belirlenir ve tüm bacaklarında korunur — aynı fiziksel aracın rotası boyunca tutarlı
"Araç ID" kalması için gerekli. Konsolidasyonlu (ara duraklı) bir serviste ara durakta
yeni yük binmesi teorik olarak bir kopyanın bacak bazında kapasiteyi aşmasına yol açabilir;
bu, çok nadir bir kenar durumdur ve bu issue'nun kapsamında tam bir çok-emtia bin-packing
çözücüsü yazılmamıştır (§ kapsam notu, `kayan_pencere.py` ile aynı).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import config
from katman2_planlama.plan_yazici import AracPlan, BacakAtama, TalepAtama
from katman2_planlama.servis import Servis

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar


@dataclass(frozen=True)
class Parca:
    """Bir talebin (ya da bölünmüş parçasının) uçtan uca yolculuğu.

    `adimlar`: sırayla kat ettiği (arac_indeksi, bacak_no) çiftleri — yalnız gerçek
    araç bacakları, bekleme kenarları temsil edilmez (bekleme zaten iki adım
    arasındaki zaman farkından örtük olarak çıkar).
    """
    talep_id: str
    desi: float
    dogus_ani: datetime
    sla_bitis_ani: datetime
    adimlar: tuple[tuple[int, int], ...]


def _ellecleme_dk(desi: float) -> int:
    return math.ceil(desi * config.ELLECLEME_DK_PER_DESI)


def _seyir_dk(seyir_saat: float) -> int:
    return math.ceil(seyir_saat * 60)


def _sla_ceza_tl(gecikme_dk: float, desi: float) -> float:
    if gecikme_dk <= 0:
        return 0.0
    gecikme_saat = math.ceil(gecikme_dk / 60.0)
    return round(desi * gecikme_saat * config.SLA_CEZA_TL_PER_DESI_SAAT, 2)


def bin_pack(
    talepler: list[tuple[str, float]],
    kapasiteler: list[tuple[int, float]],
) -> dict[str, list[tuple[int, float]]]:
    """`talepler`i ([(talep_id, desi), ...]) `kapasiteler`e ([(hedef_id, kapasite), ...])
    sırayla (ilk uyanı doldur, taşarsa böl) dağıtır.

    Çağıran `Σ kapasite >= Σ desi` garantisi vermelidir (MILP/greedy zaten bunu sağlar —
    bacak/servis kapasitesi kısıtı). Döner: `{talep_id: [(hedef_id, o_hedefe_giden_desi), ...]}`.
    """
    kalan_hedefler = [[hid, kap] for hid, kap in kapasiteler]
    sonuc: dict[str, list[tuple[int, float]]] = {}
    hedef_idx = 0

    for talep_id, desi in talepler:
        kalan_desi = desi
        dagilim: list[tuple[int, float]] = []
        while kalan_desi > 1e-9:
            while hedef_idx < len(kalan_hedefler) and kalan_hedefler[hedef_idx][1] <= 1e-9:
                hedef_idx += 1
            if hedef_idx >= len(kalan_hedefler):
                raise ValueError(
                    f"bin_pack: kapasite yetersiz, {kalan_desi} desi karşılanamadı "
                    f"(talep {talep_id})."
                )
            hedef_id, hedef_kapasite = kalan_hedefler[hedef_idx]
            pay = min(kalan_desi, hedef_kapasite)
            dagilim.append((hedef_id, pay))
            kalan_hedefler[hedef_idx][1] -= pay
            kalan_desi -= pay
        sonuc[talep_id] = dagilim

    return sonuc


def parcalara_ayir(
    dagilim: dict[str, list[tuple[int, float]]],
    adim_uret,
    dogus_ani_map: dict[str, datetime],
    sla_bitis_map: dict[str, datetime],
) -> list[Parca]:
    """`bin_pack` çıktısını `Parca` listesine çevirir; bölünen talepler için akış
    ayrıştırmasıyla (`emtia_graf.akis_ayristir`) aynı `D00001-1`, `D00001-2` kuralı
    uygulanır (yalnız gerçekten bölündüyse suffix eklenir).

    `adim_uret(hedef_id) -> tuple[tuple[int,int], ...]`: bir hedefin (arac_indeksi
    veya (arac_indeksi,bacak_no)) hangi `adimlar` çiftine karşılık geldiğini üretir.
    """
    parcalar: list[Parca] = []
    for talep_id, dagilan in dagilim.items():
        bolundu = len(dagilan) > 1
        for i, (hedef_id, desi) in enumerate(dagilan, start=1):
            parca_id = f"{talep_id}-{i}" if bolundu else talep_id
            parcalar.append(Parca(
                talep_id=parca_id,
                desi=desi,
                dogus_ani=dogus_ani_map[talep_id],
                sla_bitis_ani=sla_bitis_map[talep_id],
                adimlar=adim_uret(hedef_id),
            ))
    return parcalar


def post_pass(
    kisitlar: "Kisitlar",
    servisler: list[Servis],
    parcalar: list[Parca],
) -> list[AracPlan]:
    """Gerçek yükle zaman/maliyet düzeltmesi. `servisler[i]` = commit edilmiş i'inci
    araç; `parcalar` bu araçların bacaklarını gerçekte kimin/ne kadarının kullandığını
    anlatır (bkz. `Parca`).

    Algoritma: her (arac_indeksi, bacak_no) çiftinin gerçek kalkış/varış anı, o bacağı
    kullanan tüm parçaların "hazır anı"na (önceki adımlarının gerçek varışı ya da
    ilk adımsa doğuş anı) ve gerçek yüküne (o bacaktaki parçaların desi toplamı) göre
    hesaplanır — memoization ile (bacaklar arası bağımlılık bir DAG, döngü içermez:
    bir aracın bacak_no'su kendi rotası boyunca artar, bir parçanın adım indeksi kendi
    yolculuğu boyunca artar).
    """
    # bacak_no -> o bacağı kullanan parçalar (adim indeksiyle birlikte)
    bacak_parcalari: dict[tuple[int, int], list[tuple[Parca, int]]] = {}
    for parca in parcalar:
        for adim_idx, adim in enumerate(parca.adimlar):
            bacak_parcalari.setdefault(adim, []).append((parca, adim_idx))

    kalkis_cache: dict[tuple[int, int], datetime] = {}
    varis_cache: dict[tuple[int, int], datetime] = {}

    def _hazir_ani(parca: Parca, adim_idx: int) -> datetime:
        if adim_idx == 0:
            # `parca.dogus_ani` yükün GERÇEK doğuş anıdır (SLA için doğru), ama
            # aracın kendisi kayan pencerede belirli bir GÜNE yapısal olarak commit
            # edilmiştir (o günün elleçleme/tır kapasitesi buna göre hesaba katıldı).
            # Gerçek süre kısaldığı için kalkışı erkene çekmek (§5.4) o günün
            # İÇİNDE serbesttir, ama aracın kendi commit edildiği güne AİT olmayan
            # (daha önceki) bir güne sıçraması kapasite muhasebesini bozar — o yüzden
            # doğuş anı, aracın yapısal gününün başlangıcına kenetlenir (clamp).
            arac_indeksi, _ = parca.adimlar[0]
            gun_baslangici = datetime.combine(servisler[arac_indeksi].cikis_ani.date(), datetime.min.time())
            return max(parca.dogus_ani, gun_baslangici)
        onceki_adim = parca.adimlar[adim_idx - 1]
        return _bacak_varis(onceki_adim)

    def _bacak_yuk(adim: tuple[int, int]) -> float:
        return sum(p.desi for p, _ in bacak_parcalari[adim])

    def _bacak_kalkis(adim: tuple[int, int]) -> datetime:
        if adim in kalkis_cache:
            return kalkis_cache[adim]
        hazir_anlari = [_hazir_ani(p, i) for p, i in bacak_parcalari[adim]]
        hazir = max(hazir_anlari)
        ell_dk = _ellecleme_dk(_bacak_yuk(adim))
        kalkis = hazir + timedelta(minutes=ell_dk)
        kalkis_cache[adim] = kalkis
        return kalkis

    def _bacak_varis(adim: tuple[int, int]) -> datetime:
        if adim in varis_cache:
            return varis_cache[adim]
        arac_indeksi, bacak_no = adim
        servis = servisler[arac_indeksi]
        cikis_tm, varis_tm = servis.bacaklar()[bacak_no]
        kalkis = _bacak_kalkis(adim)
        seyir = _seyir_dk(kisitlar.seyir_saat(cikis_tm, varis_tm, servis.arac_tipi))
        ell_dk = _ellecleme_dk(_bacak_yuk(adim))
        varis = kalkis + timedelta(minutes=seyir) + timedelta(minutes=ell_dk)
        varis_cache[adim] = varis
        return varis

    # Her aracın bacak bazında (talep listesi + kalkış/varış) planı
    arac_bacaklari: list[list[BacakAtama]] = [[] for _ in servisler]
    arac_maliyeti: list[float] = [0.0 for _ in servisler]

    for arac_indeksi, servis in enumerate(servisler):
        arac = kisitlar.arac_tipleri[servis.arac_tipi]
        saatlik = arac.kiralik_saatlik_tl if servis.kiralik else arac.spot_saatlik_tl
        km_ucret = arac.kiralik_km_tl if servis.kiralik else arac.spot_km_tl
        toplam_dk = 0
        toplam_km = 0

        for bacak_no, (cikis_tm, varis_tm) in enumerate(servis.bacaklar()):
            adim = (arac_indeksi, bacak_no)
            if adim not in bacak_parcalari:
                continue  # bu bacağı kullanan hiçbir parça yok (olmamalı, güvenlik)

            kalkis = _bacak_kalkis(adim)
            varis = _bacak_varis(adim)
            seyir_dk = _seyir_dk(kisitlar.seyir_saat(cikis_tm, varis_tm, servis.arac_tipi))
            yuk = _bacak_yuk(adim)

            toplam_dk += _ellecleme_dk(yuk) * 2 + seyir_dk
            toplam_km += kisitlar.mesafe_km(cikis_tm, varis_tm)

            talepler: list[TalepAtama] = []
            for parca, adim_idx in bacak_parcalari[adim]:
                son_bacak = adim_idx == len(parca.adimlar) - 1
                sla_ceza = 0.0
                if son_bacak:
                    gecikme_dk = (varis - parca.sla_bitis_ani).total_seconds() / 60.0
                    sla_ceza = _sla_ceza_tl(gecikme_dk, parca.desi)
                talepler.append(TalepAtama(
                    talep_id=parca.talep_id, desi=parca.desi,
                    son_bacak=son_bacak, sla_ceza=sla_ceza,
                ))

            arac_bacaklari[arac_indeksi].append(BacakAtama(
                cikis=cikis_tm, varis=varis_tm,
                cikis_ani=kalkis, varis_ani=varis,
                seyir_dk=seyir_dk, talepler=talepler,
            ))

        arac_maliyeti[arac_indeksi] = round(
            saatlik * toplam_dk / 60.0 + km_ucret * toplam_km, 2
        )

    return [
        AracPlan(
            arac_tipi=servis.arac_tipi, kiralik=servis.kiralik,
            bacaklar=arac_bacaklari[i], toplam_maliyet=arac_maliyeti[i],
        )
        for i, servis in enumerate(servisler)
        if arac_bacaklari[i]  # hiç parçası olmayan (kullanılmamış) commit edilmemiş olmalı
    ]
