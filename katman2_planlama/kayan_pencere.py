# -*- coding: utf-8 -*-
"""Katman 2 · Kayan pencere sürücüsü (mimari §5.4, issue #21).

7 günü tek MILP çağrısında çözmek yerine `config.KAYAN_PENCERE_GUN` (3) günlük
pencerelerle ilerler: her pencerede greedy taban çizgisi (issue #12-16, DEĞİŞTİRİLMEDEN)
hem maliyet kıyası hem CP-SAT warm-start için kullanılır, yalnız pencerenin ilk günü
commit edilir, pencere `config.KAYAN_PENCERE_ADIM_GUN` (1) gün ilerler. Commit edilmeyen
(hâlâ karşılanmamış) desi bir sonraki pencerenin girdisine otomatik dahil olur.

MILP'in her pencerede greedy'den kötü olmaması, CP-SAT hint'inin "garanti"sine değil,
açık kıyas + fallback'e dayanır: her pencerede iki taraf da post-pass'ten geçirilip
gerçek maliyetleri karşılaştırılır, ucuz olan commit edilir (bkz. `kayan_pencere_coz`).

Ölçek notu: `havuz_uret` (#18, dokunulmuyor) adayları `kisitlar.aktif_hatlar`'ın TAMAMI
için üretir — talep büyüklüğüne göre ölçeklenmez. Bu modül onu (yalnız kiralık zinciri
için gerekli tek çağrı dışında) TEK SEFER çağırıp sonuçları pencereye göre filtreler;
289 hatlık gerçek `kisitlar` ile çağrıldığında `havuz_uret`'in kendisi zaten belgelenmiş
büyük ölçek riskini taşır (§5.4). Testler bu yüzden (test_milp_cozucu.py'nin gerçek veri
testiyle aynı ilkeyle) sınırlı `aktif_hatlar`'lı bir `Kisitlar` kullanır.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.emtia_graf import akis_ayristir, emtia_olustur, graf_kur
from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir
from katman2_planlama.milp_cozucu import milp_coz
from katman2_planlama.plan_yazici import AracPlan
from katman2_planlama.post_pass import Parca, bin_pack, post_pass
from katman2_planlama.servis import Servis
from katman2_planlama.servis_havuzu import ServisAdayi, havuz_uret
from katman2_planlama.spot_placer import spot_arac_ata
from katman2_planlama.tir_slot_tahsis import tir_slot_tahsis

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

GUN_SAYISI = 7


@dataclass(frozen=True)
class PencereSonucu:
    pencere_no: int
    ilk_gun: date
    son_gun: date
    greedy_maliyet_tl: float
    milp_maliyet_tl: float | None
    secilen: str            # "greedy" | "milp"
    milp_durum: str
    milp_gap: float | None
    sure_sn: float
    not_: str


@dataclass(frozen=True)
class KayanPencereSonucu:
    arac_planlari: list[AracPlan]
    pencere_raporu: pd.DataFrame
    toplam_sure_sn: float


# --------------------------------------------------------------------------
# Greedy taban çizgisi — tüm ufuk için TEK SEFER (kiralik_placer'ın kendisi zaten
# 7 günü sabit varsayıyor; tir_slot_tahsis/spot_arac_ata pencere ile tekrar tekrar
# çağrılmaz — bkz. modül docstring, kapasite defterlerinin pencereler arası
# sızdırılmaması için).
# --------------------------------------------------------------------------

def _bucket_anahtari(servis: Servis) -> tuple[str, str, date]:
    return (servis.duraklar[0], servis.duraklar[-1], servis.cikis_ani.date())


def _zaman_sirali_bin_pack(
    kaynaklar: list[tuple[str, float, date]],
    hedefler: list[tuple[int, float, date]],
) -> dict[str, list[tuple[int, float]]]:
    """`post_pass.bin_pack`'in zaman-öncelikli hali: bir kaynak (id, desi, en_erken_gun)
    yalnız KENDİ gününde ya da SONRASINDA kalkan hedeflere (hedef_id, kapasite, gun)
    atanabilir — bir araç henüz doğmamış yükü taşıyamaz (spot_placer'ın ertelemesi,
    issue #15, bir servisin kalkış gününü onu doğuran talebin gününden ileri kaydırabilir).
    Kaynaklar en erken güne, hedefler kalkış gününe göre işlenir; her kaynak uygun
    hedefler arasında kalkış sırasına göre ilk uyanı doldurur.
    """
    kalan = sorted(
        ([hid, kap, gun] for hid, kap, gun in hedefler), key=lambda h: h[2]
    )
    sonuc: dict[str, list[tuple[int, float]]] = {}

    for talep_id, desi, en_erken_gun in sorted(kaynaklar, key=lambda k: k[2]):
        kalan_desi = desi
        dagilim: list[tuple[int, float]] = []
        for hedef in kalan:
            if kalan_desi <= 1e-9:
                break
            if hedef[2] < en_erken_gun or hedef[1] <= 1e-9:
                continue
            pay = min(kalan_desi, hedef[1])
            dagilim.append((hedef[0], pay))
            hedef[1] -= pay
            kalan_desi -= pay
        if kalan_desi > 1e-9:
            raise ValueError(
                f"_zaman_sirali_bin_pack: {talep_id} için {kalan_desi} desi "
                f"uygun (zamanca geçerli) hedef bulunamadan karşılanamadı."
            )
        sonuc[talep_id] = dagilim

    return sonuc


def _greedy_tam_plan(
    kisitlar: "Kisitlar", talep_df: pd.DataFrame, tahmin_baslangic: datetime,
    *, gercek_dogus_ani: dict[str, datetime] | None = None,
) -> tuple[list[Servis], list[Parca]]:
    """Kiralık -> tır slotu -> spot zincirini (değiştirmeden) çalıştırır, sonucu
    orijinal `talep_id` satırlarına `bin_pack` ile dağıtır (§9 "hiçbir yük dışarıda
    kalmaz" garantisiyle bucket'ın tamamı her zaman committed servislere sığar).

    `gercek_dogus_ani`: kayan pencere sürücüsü, bir önceki penceden devreden yükü
    bu fonksiyona GÜNCEL pencerenin başlangıç gününe "tarih"i kaydırılmış olarak
    verir — aksi halde kiralık/tır/spot'un kendi iç gün eşleştirmesi hep ORİJİNAL
    (artık geçmişte kalan) günü arar ve devreden yükü hiçbir zaman yeniden
    zamanlayamaz (bu issue'nun geliştirme sürecinde canlı testle yakalanmış bir
    hata). Bu harita, SLA'ya giren gerçek doğuş anını (satırın kaydırılmış
    "tarih"inden değil) korumak için kullanılır.
    """
    kiralik_servisler, kalan_kiralik, kapasite, _ = kiralik_servisleri_yerlestir(
        kisitlar, talep_df, tahmin_baslangic
    )
    # `kiralik_servisleri_yerlestir`'in `kalan_talep_df`'i YALNIZ kiralık hatların
    # (kisitlar.kiralik_hatlar) karşılanmayan kısmını içerir (bkz. tests/test_tir_slot_tahsis.py
    # kabul testleri — tir_slot_tahsis'e giden df kiralık-dışı hatlar için doğrudan
    # `talep_df`'ten kurulur). Kiralık-dışı hatların TAMAMI (hiç kiralık dokunmadığı için)
    # olduğu gibi eklenir.
    kiralik_hat_ciftleri = {(h.cikis, h.varis) for h in kisitlar.kiralik_hatlar}
    kiralik_disi = talep_df[
        ~talep_df.apply(lambda r: (r["cikis"], r["varis"]) in kiralik_hat_ciftleri, axis=1)
    ]
    kalan_kiralik_disi = kiralik_disi.rename(columns={"toplam_desi": "kalan_desi"})[
        ["cikis", "varis", "tarih", "slot", "kalan_desi"]
    ]
    kalan1 = pd.concat([kalan_kiralik, kalan_kiralik_disi], ignore_index=True)

    tir_servisler, kalan2, kapasite, _ = tir_slot_tahsis(kisitlar, kalan1, kapasite)
    spot_servisler, _rapor_spot, _ell = spot_arac_ata(
        kisitlar, kalan2, kapasite, tahmin_baslangic
    )
    servisler = kiralik_servisler + tir_servisler + spot_servisler

    # bucket (cikis,varis) -> [servis_indeksi, ...] — TARİH bilerek bucket anahtarına
    # dahil edilmiyor: spot_placer kapasite taşınca ("erteleme") aynı talebi DAHA GEÇ
    # bir güne kaydırabilir (issue #15), o zaman servisin kalkış günü, kendisini
    # doğuran talebin ORİJİNAL gününden farklı olur. Tarihe göre bucketlarsak o
    # ertelenmiş servisin bucket'ı hiçbir orijinal talep satırıyla eşleşmez ve
    # taşıdığı desi parça listesinde hiç temsil edilmeden kaybolur. Bunun yerine
    # aşağıda `_zaman_sirali_bin_pack` ile kaynak (talebin doğuş günü) <= hedef
    # (aracın kalkış günü) önceliği ayrıca zaten korunuyor — bir araç, henüz
    # doğmamış yükü taşıyamaz kuralı burada garanti ediliyor.
    bucket_servisler: dict[tuple[str, str], list[int]] = {}
    for i, servis in enumerate(servisler):
        cikis, varis, _ = _bucket_anahtari(servis)
        bucket_servisler.setdefault((cikis, varis), []).append(i)

    parcalar: list[Parca] = []
    for (cikis, varis), servis_idxleri in bucket_servisler.items():
        satirlar = talep_df[(talep_df["cikis"] == cikis) & (talep_df["varis"] == varis)]
        if satirlar.empty:
            continue

        # `dogus_map`: SLA'ya giren GERÇEK doğuş anı (varsa override, yani orijinal —
        # kaydırılmamış — an). `kaynaklar`ın `en_erken_gun`ü ise kasıtlı olarak
        # SATIRIN KENDİ ("tarih") gününü kullanır (override'ı DEĞİL): bu satırın
        # tarihi çağıran tarafından zaten pencere başlangıcına kaydırılmış olabilir
        # (devreden yük) — gerçek (eski) doğuş anını precedence kontrolünde kullanırsak
        # bin-pack, aracı kaydırmanın amacını es geçip yükü YİNE eski (artık commit
        # penceresi kapanmış) bir güne atayabilir.
        dogus_map = {
            r.talep_id: (gercek_dogus_ani or {}).get(r.talep_id, _dogus_ani(r.tarih, r.slot))
            for r in satirlar.itertuples(index=False)
        }
        kaynaklar = [
            (r.talep_id, float(r.toplam_desi), _dogus_ani(r.tarih, r.slot).date())
            for r in satirlar.itertuples(index=False)
        ]
        hedefler = [
            (
                idx,
                float(kisitlar.arac_tipleri[servisler[idx].arac_tipi].kapasite_desi),
                servisler[idx].cikis_ani.date(),
            )
            for idx in servis_idxleri
        ]
        dagilim = _zaman_sirali_bin_pack(kaynaklar, hedefler)

        sla_gun = kisitlar.sla_gun(cikis, varis)
        sla_map = {tid: dogus_map[tid] + timedelta(days=sla_gun) for tid in dogus_map}

        for talep_id, dagilan in dagilim.items():
            bolundu = len(dagilan) > 1
            for i, (servis_idx, desi) in enumerate(dagilan, start=1):
                parca_id = f"{talep_id}-{i}" if bolundu else talep_id
                parcalar.append(Parca(
                    talep_id=parca_id, desi=desi,
                    dogus_ani=dogus_map[talep_id], sla_bitis_ani=sla_map[talep_id],
                    adimlar=((servis_idx, 0),),   # greedy: her servis tek bacaklı (direkt)
                ))

    return servisler, parcalar


def _dogus_ani(tarih, slot: str) -> datetime:
    saat = int(str(slot).split(":")[0])
    tarih_date = pd.Timestamp(tarih).date()
    return datetime.combine(tarih_date, datetime.min.time().replace(hour=saat))


# --------------------------------------------------------------------------
# Greedy -> CP-SAT warm-start adaptörü
# --------------------------------------------------------------------------

def _greedy_ipucu_uret(
    greedy_servisler: list[Servis], servis_adaylari: tuple[ServisAdayi, ...],
) -> dict[ServisAdayi, int]:
    """Greedy'nin ürettiği servisleri havuzdaki adaylarla eşleştirip sayar.

    Tam (dakikaya kadar) değer eşleşmesi ARANMAZ — greedy kalkışı GERÇEK yükle
    (§9), havuz adayının kalkışı ise §5.4'ün "zaman sabitlenir" kuralı gereği
    her zaman TAM KAPASİTE varsayımıyla hesaplanır; ikisi aynı (rota, tip, gün,
    slot) kaynaklı olsa bile dakikası neredeyse hiç örtüşmez (canlı ölçümle
    doğrulandı: gerçek yükte kalkış her zaman havuzunkinden erken/eşittir).
    Bunun yerine her greedy servis, AYNI rotadaki (araç tipi, kiralık, duraklar)
    havuz adayları arasından, kendi kalkışına EN YAKIN VE ONDAN GERİDE OLMAYAN
    (havuz her zaman >= gerçek olduğu için) adaya eşlenir. Hâlâ eşleşmeyenler
    (rota havuzda hiç yoksa) sessizce atlanır — hint best-effort'tür,
    "greedy'den kötü olmama" garantisi ayrı bir kıyas+fallback mekanizmasından
    gelir (`kayan_pencere_coz`), bu ipucundan değil.
    """
    rota_havuzu: dict[tuple, list[ServisAdayi]] = {}
    for aday in servis_adaylari:
        rota = (aday.servis.arac_tipi, aday.servis.kiralik, aday.servis.duraklar)
        rota_havuzu.setdefault(rota, []).append(aday)
    for rota, adaylar in rota_havuzu.items():
        adaylar.sort(key=lambda a: a.servis.cikis_ani)

    sayim = Counter(greedy_servisler)
    ipucu: dict[ServisAdayi, int] = {}
    for servis, sayi in sayim.items():
        rota = (servis.arac_tipi, servis.kiralik, servis.duraklar)
        adaylar = rota_havuzu.get(rota)
        if not adaylar:
            continue
        gec_esit = [a for a in adaylar if a.servis.cikis_ani >= servis.cikis_ani]
        secilen = (
            min(gec_esit, key=lambda a: a.servis.cikis_ani) if gec_esit
            else min(adaylar, key=lambda a: abs((a.servis.cikis_ani - servis.cikis_ani).total_seconds()))
        )
        ipucu[secilen] = ipucu.get(secilen, 0) + sayi
    return ipucu


# --------------------------------------------------------------------------
# MILP çözümünü yerel (servisler, parçalar) haline çevirme — fiziksel kopya
# (x[s] > 1) ayrıştırması `bin_pack` ile (bkz. post_pass.py kapsam notu).
# --------------------------------------------------------------------------

def _bacak_no_bul(servis: Servis, kenar) -> int:
    for i, (c, v) in enumerate(servis.bacaklar()):
        if c == kenar.kaynak.tm and v == kenar.hedef.tm:
            return i
    raise ValueError(f"Kenar {kenar} servis {servis} rotasında bulunamadı.")


def _milp_parcalari_uret(
    sonuc, emtialar, eslesme_tablosu: pd.DataFrame,
) -> tuple[list[Servis], list[Parca]]:
    servisler: list[Servis] = []
    aday_indeksleri: dict[ServisAdayi, list[int]] = {}
    for aday, sayi in sonuc.x.items():
        if sayi <= 0:
            continue
        indeksler = []
        for _ in range(sayi):
            indeksler.append(len(servisler))
            servisler.append(aday.servis)
        aday_indeksleri[aday] = indeksler

    eslesme_by_emtia = {e_id: df for e_id, df in eslesme_tablosu.groupby("emtia_id")}
    ham_parcalar: list[dict] = []
    for emtia in emtialar:
        akislar = sonuc.kenar_akislari.get(emtia.emtia_id, {})
        eslesme_e = eslesme_by_emtia.get(emtia.emtia_id)
        if not akislar or eslesme_e is None:
            continue
        parcalar_e, _ = akis_ayristir(emtia.emtia_id, eslesme_e, akislar)
        dogus_by_talep = eslesme_e.set_index("talep_id")["dogus_ani"].to_dict()
        for p in parcalar_e:
            servis_bacaklari = [k for k in p["bacaklar"] if k.tur == "servis"]
            if not servis_bacaklari:
                continue
            kok_id = p["talep_id"].split("-")[0]
            dogus = dogus_by_talep.get(kok_id, dogus_by_talep.get(p["talep_id"]))
            ham_parcalar.append({
                "talep_id": p["talep_id"], "desi": p["desi"],
                "dogus_ani": dogus, "sla_bitis_ani": emtia.sla_bitis_ani,
                "kenarlar": servis_bacaklari,
            })

    # aday başına fiziksel kopya paylaşımı (yalnız x[aday] > 1 için)
    parca_instance: dict[tuple[str, ServisAdayi], list[tuple[int, float]]] = {}
    for aday, indeksler in aday_indeksleri.items():
        if len(indeksler) <= 1:
            continue
        ilgili = [
            (hp["talep_id"], hp["desi"]) for hp in ham_parcalar
            if any(k.servis_adayi == aday for k in hp["kenarlar"])
        ]
        if not ilgili:
            continue
        dagilim = bin_pack(ilgili, [(idx, float(aday.kapasite_desi)) for idx in indeksler])
        for talep_id, pay in dagilim.items():
            parca_instance[(talep_id, aday)] = pay

    parcalar: list[Parca] = []
    for hp in ham_parcalar:
        parcalar.extend(_ham_parcayi_boluster(hp, aday_indeksleri, parca_instance))

    return servisler, parcalar


def _ham_parcayi_boluster(
    hp: dict,
    aday_indeksleri: dict[ServisAdayi, list[int]],
    parca_instance: dict[tuple[str, ServisAdayi], list[tuple[int, float]]],
) -> list[Parca]:
    parcalar_dict: dict[str, tuple[float, list[tuple[int, int]]]] = {"": (hp["desi"], [])}

    for kenar in hp["kenarlar"]:
        aday = kenar.servis_adayi
        indeksler = aday_indeksleri[aday]
        bacak_no = _bacak_no_bul(aday.servis, kenar)
        yeni: dict[str, tuple[float, list[tuple[int, int]]]] = {}

        if len(indeksler) == 1:
            arac_idx = indeksler[0]
            for suf, (desi, adimlar) in parcalar_dict.items():
                yeni[suf] = (desi, adimlar + [(arac_idx, bacak_no)])
        else:
            dagilim = parca_instance.get((hp["talep_id"], aday), [(indeksler[0], hp["desi"])])
            for suf, (desi, adimlar) in parcalar_dict.items():
                if len(dagilim) == 1:
                    arac_idx = dagilim[0][0]
                    yeni[suf] = (desi, adimlar + [(arac_idx, bacak_no)])
                else:
                    for j, (inst_idx, pay) in enumerate(dagilim, start=1):
                        oran = pay / hp["desi"] if hp["desi"] else 0.0
                        alt_desi = desi * oran
                        alt_suf = f"{suf}-{j}"
                        yeni[alt_suf] = (alt_desi, adimlar + [(inst_idx, bacak_no)])
        parcalar_dict = yeni

    return [
        Parca(
            talep_id=hp["talep_id"] + suf, desi=desi,
            dogus_ani=hp["dogus_ani"], sla_bitis_ani=hp["sla_bitis_ani"],
            adimlar=tuple(adimlar),
        )
        for suf, (desi, adimlar) in parcalar_dict.items()
        if desi > 1e-9
    ]


# --------------------------------------------------------------------------
# Pencere içi commit ayrımı — bir parçanın İLK bacağı pencerenin ilk gününde
# kalkıyorsa TÜMÜ commit edilir (§ kapsam notu: kısmi/ara-TM'den devir bu
# issue'nun kapsamı dışında, sadeleştirme belgelenmiştir); son pencerede
# pencerenin TÜM günleri commit edilir (devredecek başka pencere yok).
# --------------------------------------------------------------------------

def _commit_ayir(
    servisler: list[Servis], parcalar: list[Parca], ilk_gun: date, son_gun_dahil: date | None,
) -> tuple[list[Servis], list[Parca]]:
    committed_idx: dict[int, int] = {}
    yeni_servisler: list[Servis] = []
    yeni_parcalar: list[Parca] = []

    def _commit_mi(parca: Parca) -> bool:
        ilk_arac_idx = parca.adimlar[0][0]
        gun = servisler[ilk_arac_idx].cikis_ani.date()
        if son_gun_dahil is not None:
            return ilk_gun <= gun <= son_gun_dahil
        return gun == ilk_gun

    for parca in parcalar:
        if not _commit_mi(parca):
            continue
        yeni_adimlar = []
        for arac_idx, bacak_no in parca.adimlar:
            if arac_idx not in committed_idx:
                committed_idx[arac_idx] = len(yeni_servisler)
                yeni_servisler.append(servisler[arac_idx])
            yeni_adimlar.append((committed_idx[arac_idx], bacak_no))
        yeni_parcalar.append(Parca(
            talep_id=parca.talep_id, desi=parca.desi,
            dogus_ani=parca.dogus_ani, sla_bitis_ani=parca.sla_bitis_ani,
            adimlar=tuple(yeni_adimlar),
        ))

    return yeni_servisler, yeni_parcalar


def _plan_maliyeti(arac_planlari: list[AracPlan]) -> float:
    return round(sum(
        arac.toplam_maliyet + sum(t.sla_ceza for b in arac.bacaklar for t in b.talepler)
        for arac in arac_planlari
    ), 2)


def _kok_id(talep_id: str) -> str:
    return talep_id.split("-")[0]


# --------------------------------------------------------------------------
# Ana sürücü
# --------------------------------------------------------------------------

def kayan_pencere_coz(
    kisitlar: "Kisitlar",
    talep_df: pd.DataFrame,
    tahmin_baslangic: datetime,
    *,
    pencere_gun: int = config.KAYAN_PENCERE_GUN,
    adim_gun: int = config.KAYAN_PENCERE_ADIM_GUN,
    pencere_zaman_limit_sn: float = config.KAYAN_PENCERE_ZAMAN_LIMIT_SN,
) -> KayanPencereSonucu:
    t0 = time.perf_counter()

    havuz = havuz_uret(kisitlar, talep_df, tahmin_baslangic)

    kalan_desi: dict[str, float] = {
        r.talep_id: float(r.toplam_desi) for r in talep_df.itertuples(index=False)
    }
    talep_meta = talep_df.set_index("talep_id")[["cikis", "varis", "tarih", "slot"]].to_dict("index")

    tum_arac_planlari: list[AracPlan] = []
    pencere_satirlari: list[dict] = []

    pencere_no = 0
    ilk_gun = tahmin_baslangic.date()
    while ilk_gun < tahmin_baslangic.date() + timedelta(days=GUN_SAYISI):
        pencere_baslangic_gun = ilk_gun
        pencere_bitis_gun = min(
            ilk_gun + timedelta(days=pencere_gun),
            tahmin_baslangic.date() + timedelta(days=GUN_SAYISI),
        )
        son_pencere = pencere_bitis_gun >= tahmin_baslangic.date() + timedelta(days=GUN_SAYISI)
        son_gun_dahil = pencere_bitis_gun - timedelta(days=1) if son_pencere else None

        t_pencere0 = time.perf_counter()

        # Pencerenin girdisi: hâlâ karşılanmamış desi + tarihi pencere içinde/öncesinde olan.
        # `pencere_talep_df` (MILP'e gider) ORİJİNAL tarihi korur — MILP zaten devreden yükü
        # bekleme kenarlarıyla doğru ele alıyor (§5.4, issue #20). `pencere_talep_df_greedy`
        # ise devreden (pencere başlangıcından ÖNCEKİ tarihli) satırların "tarih"ini pencere
        # başlangıcına kaydırır — greedy'nin (kiralık/tır/spot) kendi iç gün eşleştirmesi
        # yalnız satırın KENDİ "tarih"ine bakar, MILP'in bekleme mekanizması yok; kaydırılmazsa
        # devreden yükü hep artık geçmişte kalan bir güne zamanlamaya çalışır ve hiçbir
        # pencerede "ilk gün" olarak commit edilemez (canlı testle yakalanmış bir hata).
        # `gercek_dogus_ani` gerçek SLA başlangıcını (kaydırılmamış) ayrıca taşır.
        pencere_satirlar = []
        pencere_satirlar_greedy = []
        gercek_dogus_ani: dict[str, datetime] = {}
        for talep_id, desi in kalan_desi.items():
            if desi <= 1e-9:
                continue
            meta = talep_meta[talep_id]
            orijinal_gun = pd.Timestamp(meta["tarih"]).date()
            if orijinal_gun >= pencere_bitis_gun:
                continue
            pencere_satirlar.append({
                "talep_id": talep_id, "tarih": meta["tarih"], "cikis": meta["cikis"],
                "varis": meta["varis"], "slot": meta["slot"], "toplam_desi": desi,
            })
            greedy_tarih = (
                pd.Timestamp(pencere_baslangic_gun) if orijinal_gun < pencere_baslangic_gun
                else meta["tarih"]
            )
            pencere_satirlar_greedy.append({
                "talep_id": talep_id, "tarih": greedy_tarih, "cikis": meta["cikis"],
                "varis": meta["varis"], "slot": meta["slot"], "toplam_desi": desi,
            })
            gercek_dogus_ani[talep_id] = _dogus_ani(meta["tarih"], meta["slot"])

        pencere_talep_df = pd.DataFrame(
            pencere_satirlar,
            columns=["talep_id", "tarih", "cikis", "varis", "slot", "toplam_desi"],
        )
        pencere_talep_df_greedy = pd.DataFrame(
            pencere_satirlar_greedy,
            columns=["talep_id", "tarih", "cikis", "varis", "slot", "toplam_desi"],
        )

        if pencere_talep_df.empty:
            ilk_gun += timedelta(days=adim_gun)
            pencere_no += 1
            continue

        # --- greedy tarafı: GÜNCEL kalan talebe göre TAZE çalıştırılır (önceden
        # hesaplanmış tek bir 7-günlük plandan dilimlenmez). Aksi halde greedy'nin
        # kendi dünya görüşü, önceki pencerelerde MILP'in zaten commit ettiği kısmı
        # bilmez ve daha sonraki bir pencerede "boş ama bedava" bir plan sunup
        # yanlışlıkla kazanabilir (bu issue'nun geliştirme sürecinde canlı olarak
        # yakalanmış bir hata — greedy'nin kalan_desi ile MILP'inkiyle AYNI, güncel
        # talebi görmesi gerekiyordu).
        greedy_servisler_tum, greedy_parcalar_tum = _greedy_tam_plan(
            kisitlar, pencere_talep_df_greedy, tahmin_baslangic,
            gercek_dogus_ani=gercek_dogus_ani,
        )
        greedy_servisler_p, greedy_parcalar_p = _commit_ayir(
            greedy_servisler_tum, greedy_parcalar_tum, pencere_baslangic_gun, son_gun_dahil,
        )
        greedy_planlari = post_pass(kisitlar, greedy_servisler_p, greedy_parcalar_p)
        greedy_maliyet = _plan_maliyeti(greedy_planlari)

        # --- MILP tarafı ---
        pencere_adaylari = tuple(
            aday for aday in havuz.adaylar
            if pencere_baslangic_gun <= aday.servis.cikis_ani.date() < pencere_bitis_gun
        )
        emtialar, eslesme_tablosu = emtia_olustur(pencere_talep_df, kisitlar)
        _, kenarlar = graf_kur(list(pencere_adaylari), kisitlar)

        greedy_servisler_pencere_araligi = [
            s for s in greedy_servisler_tum
            if pencere_baslangic_gun <= s.cikis_ani.date() < pencere_bitis_gun
        ]
        ipucu = _greedy_ipucu_uret(greedy_servisler_pencere_araligi, pencere_adaylari)

        milp_sonuc = milp_coz(
            kisitlar, pencere_adaylari, emtialar, eslesme_tablosu, kenarlar,
            zaman_limit_sn=pencere_zaman_limit_sn, warm_start=ipucu,
        )

        milp_maliyet = None
        milp_planlari: list[AracPlan] = []
        not_ = ""
        if milp_sonuc.durum in ("OPTIMAL", "FEASIBLE"):
            milp_servisler, milp_parcalar = _milp_parcalari_uret(
                milp_sonuc, emtialar, eslesme_tablosu,
            )
            milp_servisler_p, milp_parcalar_p = _commit_ayir(
                milp_servisler, milp_parcalar, pencere_baslangic_gun, son_gun_dahil,
            )
            milp_planlari = post_pass(kisitlar, milp_servisler_p, milp_parcalar_p)
            milp_maliyet = _plan_maliyeti(milp_planlari)
        else:
            not_ = f"MILP {milp_sonuc.durum} — greedy'ye düşüldü."

        if milp_maliyet is not None and milp_maliyet <= greedy_maliyet:
            secilen = "milp"
            secilen_planlar = milp_planlari
        else:
            secilen = "greedy"
            secilen_planlar = greedy_planlari
            if milp_maliyet is not None and not not_:
                not_ = (
                    f"MILP ({milp_maliyet:.2f} TL) greedy'yi ({greedy_maliyet:.2f} TL) "
                    f"yenemedi — muhtemelen ısınma ipucu eksik eşleşme veya süre bütçesi "
                    f"yetersizliği (durum={milp_sonuc.durum}, gap={milp_sonuc.gap})."
                )

        tum_arac_planlari.extend(secilen_planlar)

        # ledger güncelle: seçilen tarafın commit ettiği desi düşülür
        committed_desi: dict[str, float] = {}
        for arac in secilen_planlar:
            for bacak in arac.bacaklar:
                for talep in bacak.talepler:
                    if talep.son_bacak:
                        kok = _kok_id(talep.talep_id)
                        committed_desi[kok] = committed_desi.get(kok, 0.0) + talep.desi
        for kok, desi in committed_desi.items():
            if kok in kalan_desi:
                kalan_desi[kok] = max(0.0, kalan_desi[kok] - desi)

        pencere_satirlari.append(dict(
            pencere_no=pencere_no, ilk_gun=pencere_baslangic_gun, son_gun=pencere_bitis_gun,
            greedy_maliyet_tl=greedy_maliyet, milp_maliyet_tl=milp_maliyet,
            secilen=secilen, milp_durum=milp_sonuc.durum, milp_gap=milp_sonuc.gap,
            sure_sn=time.perf_counter() - t_pencere0, not_=not_,
        ))

        ilk_gun += timedelta(days=adim_gun)
        pencere_no += 1

    pencere_raporu = pd.DataFrame(pencere_satirlari)
    return KayanPencereSonucu(
        arac_planlari=tum_arac_planlari,
        pencere_raporu=pencere_raporu,
        toplam_sure_sn=time.perf_counter() - t0,
    )
