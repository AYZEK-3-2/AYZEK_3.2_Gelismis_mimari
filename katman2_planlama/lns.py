# -*- coding: utf-8 -*-
"""Katman 2 · LNS iyileştirme turu (mimari §5.5, issue #22 — "zaman kalırsa").

Böl-onar (destroy-repair): rastgele bir TM-gün komşuluğu seçilir, o komşuluğa
dokunan araçlar plandan sökülür, taşıdıkları talep küçük ölçekte (mevcut CP-SAT
çekirdeği, `milp_coz` #20) yeniden kurulur. Yalnız GERÇEK iyileşme kabul edilir
ve her aday, katman3_simulator'ın kuruş kapısından (`simulasyonu_calistir`)
geçmeden asla kabul edilmez (§5.5: "Katman 3 geçmeden hiçbir LNS çıktısı kabul
edilmez") — kabul mantığı bu yüzden hem maliyet kıyasına hem simülatör geçişine
bağlıdır, `kayan_pencere_coz`'ün "kıyasla + kötüyse düş" disiplininin aynısı.

Girdi bir `list[AracPlan]`dir (kayan_pencere_coz #21 ya da plan_uret #12-16
çıktısı) — LNS, önceki katmanın hangi algoritmayla üretildiğinden bağımsız, saf
bir İYİLEŞTİRME turudur; kendi başına bir plan üretmez, var olanı düzeltir.

Fırsat listesi (§5.5, v4 — mimarinin işaret ettiği iki somut fırsat):
  ① `_zincirleme_repair` — kıt slotlu ara TM'lerde uygun direkt Tır çiftlerini
     tek araçta birleştirir; araç ara TM'de hareket etmeden boşaltılıp yeniden
     yüklendiği için dokunuş 2'den 1'e iner (§4.1, §3). Salt birleştirme
     maliyet-nötrdür (aynı toplam seyir+elleçleme süresi tek faturada toplanır);
     GERÇEK kazanç, serbest kalan slotu değerlendirip o TM'de şu an tırsız
     (daha pahalı) taşınan başka bir talebi tıra yükseltmekten gelir — bu yüzden
     bu komşuluk hem birleştirmeyi hem (varsa) en kazançlı yükseltmeyi TEK adayda
     dener.
  ② `_tm_gun_repair` (hedef_gunler = {pik gün, pik gün + 1}) — pik gün (Pazartesi/
     Salı, §4.2) bekletme desenini MILP'in kendi SLA-cezası-farkında amacına
     yeniden çözdürerek değiştirir; "hangi yük ötelensin" kararını elle
     simüle etmek yerine mevcut çözücüye devreder.
  ③ `_tm_gun_repair` (hedef_gunler = {rastgele 1 gün}) — genel TM-gün komşuluğu,
     görev listesinin "yık-onar döngüsü" maddesinin karşılığı.

Kapsam notu (bilinçli sadeleştirme, `post_pass.py`/`kayan_pencere.py` ile aynı
ilke): `_zincirleme_repair` yalnız TÜM parçaları `son_bacak=True` olan (yani
kendi kök talebinin nihai teslimini taşıyan) tek-bacaklı Tır araçlarını eşler —
çok araçlı konsolidasyon zincirlerine karışan parçalar bu komşulukta hiç ele
alınmaz. Genel/bekletme komşulukları (`_tm_gun_repair`) ise yıkılan her aracın
paylaştığı KÖK talebi taşıyan TÜM araçları (bağlantılı bileşen kapanışı ile)
birlikte yıkarak bu sorunu yapısal olarak ortadan kaldırır (bkz.
`_baglantili_yikim_kumesi`).

`milp_cozucu.py`'nin Kısıt 5'i (tır slotu, dokunuşu bacak-ucu bazında sayar)
KASITLI OLARAK değiştirilmedi: `havuz_uret` hiçbir zaman 3+ duraklı Tır adayı
üretmediği için (yalnız `_zincirleme_repair`in KENDİ elle kurduğu servisler
3 duraklı olabilir, ve o servisler `milp_coz`'a hiç gitmez) o kısıtın ara-durak
double-count sınırlaması bu modülde hiç tetiklenmez. Ara-durak dokunuş
düzeltmesi yalnız katman3_simulator'da (issue #22 önkoşulu) yapıldı — her aday
zaten oradan geçmek ZORUNDA.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.emtia_graf import emtia_olustur, graf_kur
from katman2_planlama.kayan_pencere import _dogus_ani, _milp_parcalari_uret, _plan_maliyeti
from katman2_planlama.milp_cozucu import milp_coz
from katman2_planlama.plan_yazici import AracPlan, TalepAtama, plan_yaz
from katman2_planlama.post_pass import Parca, post_pass
from katman2_planlama.servis import Servis, maliyet_hesapla
from katman2_planlama.servis_havuzu import HavuzSonucu, havuz_uret
from katman3_simulator.kapasite import KapasiteDefter
from katman3_simulator.simulator import (
    SimulasyonHatasi,
    _tir_dokunuslarini_isle,
    simulasyonu_calistir,
)

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

GUN_SAYISI = 7
KOMSULUK_TIPLERI = ("genel", "zincirleme", "bekletme")


@dataclass(frozen=True)
class LNSAdimi:
    """Bir yık-onar denemesinin logu (iyileşme eğrisi, kabul kriteri)."""
    adim_no: int
    komsuluk_tipi: str          # "genel" | "zincirleme" | "bekletme"
    hedef: str
    onceki_maliyet_tl: float
    aday_maliyet_tl: float | None   # None -> aday hiç üretilemedi
    kabul_edildi: bool
    sebep: str
    sure_sn: float


@dataclass(frozen=True)
class LNSSonucu:
    arac_planlari: list[AracPlan]
    adimlar: pd.DataFrame
    baslangic_maliyet_tl: float
    son_maliyet_tl: float
    toplam_sure_sn: float


def _kok_id(talep_id: str) -> str:
    return talep_id.split("-")[0]


def _talep_atama_to_parca(
    talep: TalepAtama, talep_meta: dict, kisitlar: "Kisitlar", adim: tuple[int, int],
) -> Parca | None:
    """`TalepAtama`yı (AracPlan içi) yeniden `Parca`ya çevirir — kök talebin
    ORİJİNAL (tarih, slot, cikis, varis) bilgisini `talep_meta`den (tam
    `talep_df`den türetilmiş) alır; `AracPlan`/`TalepAtama` bu alanları
    saklamaz (bkz. `plan_yazici.TalepAtama`), o yüzden yeniden aranmalı.
    Kök id `talep_meta`de yoksa (tutarsız girdi) None döner — çağıran bunu
    "aday üretilemedi" olarak ele almalı.
    """
    kok = _kok_id(talep.talep_id)
    meta = talep_meta.get(kok)
    if meta is None:
        return None
    dogus = _dogus_ani(meta["tarih"], meta["slot"])
    sla_bitis = dogus + timedelta(days=kisitlar.sla_gun(meta["cikis"], meta["varis"]))
    return Parca(
        talep_id=talep.talep_id, desi=talep.desi,
        dogus_ani=dogus, sla_bitis_ani=sla_bitis, adimlar=(adim,),
    )


# --------------------------------------------------------------------------
# Genel / bekletme komşuluğu ortak makinesi: TM-gün seti seç, dokunan araçları
# (bağlantılı bileşen kapanışıyla) yık, taşıdıkları kök talebi küçük ölçekte
# yeniden kur.
# --------------------------------------------------------------------------

def _baglantili_yikim_kumesi(arac_planlari: list[AracPlan], tohum: set[int]) -> set[int]:
    """`tohum`daki araçlarla, GERÇEK bir zincir bağı üzerinden kök talep
    paylaşan tüm araçları (transitif kapanış) döner.

    Bir parçanın yolculuğu birden fazla aracı kapsıyorsa (konsolidasyon),
    yalnızca bir ucu yıkmak diğer ucunda artık var olmayan bir bacağa dayanan
    "sallanan" bir referans bırakır (ör. B'de teslim edilmiş görünen ama A->B
    bacağı yıkıldığı için hiç oraya ulaşmamış bir yük). Bu risk YALNIZCA bir
    kök talebin en az bir parçası `son_bacak=False` ise vardır (yani gerçekten
    başka bir araca devam ediyor); `son_bacak=True` olan (ör. greedy'nin büyük
    bir talebi kuyruktan tek tek "ısırıklarla" — ID bölmeden — YÜZLERCE bağımsız
    araca dağıtması, `katman2_planlama/__init__.py::_talepleri_ata`) araçlar
    birbirinden TAMAMEN bağımsızdır: her biri kendi ısırığını nihai olarak
    teslim eder, biri yıkılınca diğeri asla sallanan referans olmaz. Bu ayrımı
    yapmadan (önceki sürüm) hem gereksiz yere geniş bir yıkım kümesi hem de
    gerçek veride dakikalar süren bir performans patlaması ortaya çıktı (issue
    #22 canlı testinde bulundu, bkz. `tests/test_lns.py::
    test_baglantili_yikim_kumesi_paylasilan_ama_hepsi_nihai_kok_genisletmiyor`).

    Kapanış, yalnız YENİ eklenen araçları işleyen bir sınır (frontier) ile
    hesaplanır — önceki sürüm her turda BÜTÜN kümeyi yeniden tarıyordu, büyük
    kümelerde ikinci dereceden yavaşlıyordu.
    """
    arac_kokleri: list[set[str]] = [
        {_kok_id(t.talep_id) for b in arac.bacaklar for t in b.talepler}
        for arac in arac_planlari
    ]
    zincir_riskli_kokler: set[str] = {
        _kok_id(t.talep_id)
        for arac in arac_planlari for b in arac.bacaklar for t in b.talepler
        if not t.son_bacak
    }
    kok_araclar: dict[str, set[int]] = {}
    for i, kokler in enumerate(arac_kokleri):
        for kok in kokler:
            if kok in zincir_riskli_kokler:
                kok_araclar.setdefault(kok, set()).add(i)

    kume = set(tohum)
    sinir = list(tohum)
    while sinir:
        yeni_sinir: list[int] = []
        for i in sinir:
            for kok in arac_kokleri[i]:
                if kok not in kok_araclar:
                    continue
                for j in kok_araclar[kok]:
                    if j not in kume:
                        kume.add(j)
                        yeni_sinir.append(j)
        sinir = yeni_sinir
    return kume


def _yikilan_talebi_geri_kazan(
    arac_planlari: list[AracPlan], yikim: set[int], talep_df: pd.DataFrame,
) -> pd.DataFrame:
    """Yıkılan araçlardaki her kök talep için TOPLAM teslim edilmiş desiyi
    (`son_bacak=True` satırlarının toplamı) hesaplar, kök talebin ORİJİNAL
    (cikis, varis, tarih, slot) bilgisiyle yeniden çözülecek bir talep_df
    üretir. Hangi ara TM'lerden geçtiği kasıtlı olarak atılır — yalnız kök
    O-D-zaman kimliği ve MİKTAR korunur (kayan_pencere'nin `kalan_desi`
    defteriyle aynı ilke).
    """
    teslim_toplam: dict[str, float] = {}
    for i in yikim:
        for b in arac_planlari[i].bacaklar:
            for t in b.talepler:
                if t.son_bacak:
                    kok = _kok_id(t.talep_id)
                    teslim_toplam[kok] = teslim_toplam.get(kok, 0.0) + t.desi

    meta = talep_df.set_index("talep_id")[["cikis", "varis", "tarih", "slot"]]
    satirlar = []
    for kok, desi in teslim_toplam.items():
        if desi <= 1e-9 or kok not in meta.index:
            continue
        m = meta.loc[kok]
        satirlar.append({
            "talep_id": kok, "cikis": m["cikis"], "varis": m["varis"],
            "tarih": m["tarih"], "slot": m["slot"], "toplam_desi": desi,
        })
    return pd.DataFrame(
        satirlar, columns=["talep_id", "cikis", "varis", "tarih", "slot", "toplam_desi"],
    )


def _tm_gun_repair(
    kisitlar: "Kisitlar",
    mevcut_plan: list[AracPlan],
    talep_df: pd.DataFrame,
    havuz: HavuzSonucu,
    *,
    hedef_tmler: set[str],
    hedef_gunler: set[date],
    zaman_limit_sn: float,
) -> tuple[list[AracPlan], str] | None:
    """TM-gün komşuluğu böl-onar: `hedef_tmler`×`hedef_gunler`e dokunan araçları
    (bağlantılı bileşen kapanışıyla) yık, taşıdıkları kök talebi küçük ölçekli
    bir MILP ile (`havuz`dan filtrelenmiş bir aday alt kümesiyle) yeniden kur.

    `hedef_gunler` tek gün verilirse genel komşuluk (§5.5 "rastgele bir TM-gün
    seçilir"); iki ardışık gün (pik gün + ertesi) verilirse bekletme komşuluğu
    (§4.2) olur — MILP'in kendi SLA-cezası-farkında amacı, hangi yükün hangi
    güne kalacağını yeniden seçer.
    """
    tohum = {
        i for i, arac in enumerate(mevcut_plan)
        for b in arac.bacaklar
        if (b.cikis in hedef_tmler and b.cikis_ani.date() in hedef_gunler)
        or (b.varis in hedef_tmler and b.varis_ani.date() in hedef_gunler)
    }
    if not tohum:
        return None

    yikim = _baglantili_yikim_kumesi(mevcut_plan, tohum)
    yeniden_df = _yikilan_talebi_geri_kazan(mevcut_plan, yikim, talep_df)
    if yeniden_df.empty:
        return None

    ilgili_hatlar = {(r.cikis, r.varis) for r in yeniden_df.itertuples(index=False)}
    ilgili_gunler = [pd.Timestamp(r.tarih).date() for r in yeniden_df.itertuples(index=False)]
    alt_sinir_gun = min(ilgili_gunler)
    ust_sinir_gun = max(ilgili_gunler) + timedelta(days=config.MILP_MAX_GECIKME_GUN)

    pencere_adaylari = tuple(
        aday for aday in havuz.adaylar
        if (aday.servis.duraklar[0], aday.servis.duraklar[-1]) in ilgili_hatlar
        and alt_sinir_gun <= aday.servis.cikis_ani.date() <= ust_sinir_gun
    )
    if not pencere_adaylari:
        return None

    emtialar, eslesme_tablosu = emtia_olustur(yeniden_df, kisitlar)

    # Ölçek bekçisi (issue #22 canlı testinde bulundu): `milp_coz`'un kendi
    # ölçek notu (§5.4) "1 günlük dilim ve mini örnekler" için tasarlandığını,
    # çok günlük/geniş komşuluğun AYRI bir performans issue'su olduğunu zaten
    # söylüyor. Gerçek veride yoğun bir TM'nin 2 günlük (bekletme) komşuluğu
    # onlarca kök talep + binlerce aday üretebiliyor; f[emtia,kenar] değişken
    # sayısı emtia×aday ile büyüdüğü için model KURULUMU (solver.Solve'dan
    # ÖNCEKİ Python aşaması, `zaman_limit_sn`in HİÇ göremediği kısım) dakikalar
    # sürebiliyor — bu, LNS'in "küçük ölçekte yeniden kur" ilkesine (§5.5) ve
    # süre bütçesi garantisine aykırı. Model gerçekten büyükse onarımı hiç
    # denemeden "aday üretilemedi" olarak bırakmak, tek bir denemenin tüm
    # bütçeyi yemesinden çok daha güvenli.
    if len(emtialar) * len(pencere_adaylari) > config.LNS_MAX_MODEL_OLCEK:
        return None

    _, kenarlar = graf_kur(list(pencere_adaylari), kisitlar)
    sonuc = milp_coz(
        kisitlar, pencere_adaylari, emtialar, eslesme_tablosu, kenarlar,
        zaman_limit_sn=zaman_limit_sn,
    )
    if sonuc.durum not in ("OPTIMAL", "FEASIBLE"):
        return None

    servisler, parcalar = _milp_parcalari_uret(sonuc, emtialar, eslesme_tablosu)
    if not servisler:
        return None

    yeni_planlar = post_pass(kisitlar, servisler, parcalar)
    korunan = [arac for i, arac in enumerate(mevcut_plan) if i not in yikim]

    hedef = f"{sorted(hedef_tmler)}@{sorted(g.isoformat() for g in hedef_gunler)}"
    return korunan + yeni_planlar, hedef


# --------------------------------------------------------------------------
# Zincirleme komşuluğu (§4.1, §4.4): iki direkt Tır seferini birleştir, serbest
# kalan slotu değerlendirmek için (varsa) en kazançlı tırsız-taşınan talebi de
# aynı adımda tıra yükselt.
# --------------------------------------------------------------------------

def _zincirleme_ciftleri_bul(
    mevcut_plan: list[AracPlan],
) -> list[tuple[int, AracPlan, int, AracPlan]]:
    tir_araclari = [
        (i, arac) for i, arac in enumerate(mevcut_plan)
        if arac.arac_tipi == "Tır" and len(arac.bacaklar) == 1
        and all(t.son_bacak for t in arac.bacaklar[0].talepler)
    ]
    ciftler = []
    for i1, a1 in tir_araclari:
        b1 = a1.bacaklar[0]
        for i2, a2 in tir_araclari:
            if i1 == i2:
                continue
            b2 = a2.bacaklar[0]
            if b1.varis != b2.cikis:
                continue
            if b1.cikis == b2.varis:  # X == Y — dejenere, 2 durağa döner
                continue
            if b2.cikis_ani < b1.varis_ani:  # araç M'de olmadan yola çıkamaz
                continue
            ciftler.append((i1, a1, i2, a2))
    return ciftler


def _en_iyi_yukseltme_adayi(
    kisitlar: "Kisitlar", mevcut_plan: list[AracPlan], haric: set[int],
    m: str, gun: date, talep_meta: dict,
) -> tuple[int, Servis, list[Parca]] | None:
    """M TM'sinde zincirlemeyle serbest kalan 1 slotu, şu an tırsız taşınan ve
    tıra yükseltilmesi EN ÇOK tasarruf sağlayan TEK adaya devretmeyi dener
    (§4.1/§4.4 tasarruf mantığı — `tir_slot_tahsis._tasarruf_per_desi` ile aynı
    ilke, burada gerçek plandaki tek bir aday üzerinden). Uygun aday yoksa
    None döner; zincirleme yine de salt birleştirme olarak denenir (maliyet-
    nötr olacağından kabul turunda büyük ihtimalle reddedilir, ama bu dürüst
    bir sonuçtur — fabrikasyon bir kazanç uydurulmaz).
    """
    en_iyi = None
    en_iyi_tasarruf = 0.0
    tir_kap = kisitlar.arac_tipleri["Tır"].kapasite_desi
    gun_str = gun.strftime("%d.%m.%Y")

    for i, arac in enumerate(mevcut_plan):
        if i in haric or arac.arac_tipi == "Tır" or len(arac.bacaklar) != 1:
            continue
        b = arac.bacaklar[0]
        if b.cikis != m and b.varis != m:
            continue
        if not all(t.son_bacak for t in b.talepler):
            continue
        dokunus_gunu = b.cikis_ani.date() if b.cikis == m else b.varis_ani.date()
        if dokunus_gunu.strftime("%d.%m.%Y") != gun_str:
            continue

        toplam_desi = sum(t.desi for t in b.talepler)
        if toplam_desi > tir_kap:
            continue
        if kisitlar.mesafe_km(b.cikis, b.varis) < 100:
            continue
        if kisitlar.tir_kapasitesi.get(b.cikis, 0) <= 0 or kisitlar.tir_kapasitesi.get(b.varis, 0) <= 0:
            continue

        yeni_tir_maliyet = maliyet_hesapla(
            Servis("Tır", False, (b.cikis, b.varis), b.cikis_ani),
            {b.cikis: toplam_desi, b.varis: toplam_desi}, kisitlar,
        ).arac_maliyeti_tl
        tasarruf = arac.toplam_maliyet - yeni_tir_maliyet
        if tasarruf > en_iyi_tasarruf:
            y_servis = Servis("Tır", False, (b.cikis, b.varis), b.cikis_ani)
            y_parcalar = [
                _talep_atama_to_parca(t, talep_meta, kisitlar, (0, 0)) for t in b.talepler
            ]
            if any(p is None for p in y_parcalar):
                continue
            en_iyi = (i, y_servis, y_parcalar)
            en_iyi_tasarruf = tasarruf

    return en_iyi


def _tir_dokunus_sayisi(arac_planlari: list[AracPlan], tm: str, gun: date) -> int:
    """`tm`de `gun` günü kaç tır dokunuşu var — katman3_simulator'ın (issue #22
    önkoşulu düzeltilmiş) BİREBİR aynı sayacıyla hesaplar. LNS'in kendi
    muhasebesi ile simülatörün sayacı arasında sapma riskini bu yüzden SIFIRDIR
    (aynı fonksiyon iki kez değil, TEK fonksiyon çağrılır)."""
    if not arac_planlari:
        return 0
    plan_df = plan_yaz(arac_planlari)
    kapasite = KapasiteDefter({}, {tm: 10**9})
    _tir_dokunuslarini_isle(plan_df, kapasite)
    return int(kapasite.tir_kullanim.get((tm, gun.strftime("%d.%m.%Y")), 0))


def _zincirleme_repair(
    kisitlar: "Kisitlar", mevcut_plan: list[AracPlan], talep_meta: dict, rng: random.Random,
) -> tuple[list[AracPlan], str] | None:
    ciftler = _zincirleme_ciftleri_bul(mevcut_plan)
    if not ciftler:
        return None
    i1, a1, i2, a2 = rng.choice(ciftler)
    b1, b2 = a1.bacaklar[0], a2.bacaklar[0]
    x, m, y = b1.cikis, b1.varis, b2.varis

    yeni_servis = Servis(arac_tipi="Tır", kiralik=False, duraklar=(x, m, y), cikis_ani=b1.cikis_ani)
    parcalar: list[Parca] = []
    for t in b1.talepler:
        p = _talep_atama_to_parca(t, talep_meta, kisitlar, (0, 0))
        if p is None:
            return None
        parcalar.append(p)
    for t in b2.talepler:
        p = _talep_atama_to_parca(t, talep_meta, kisitlar, (0, 1))
        if p is None:
            return None
        parcalar.append(p)

    yikilanlar = {i1, i2}
    yeni_servisler = [yeni_servis]

    yukseltme = _en_iyi_yukseltme_adayi(kisitlar, mevcut_plan, yikilanlar, m, b1.varis_ani.date(), talep_meta)
    if yukseltme is not None:
        i3, y_servis, y_parcalar = yukseltme
        yikilanlar.add(i3)
        yeni_servisler.append(y_servis)
        parcalar.extend(y_parcalar)

    yeni_planlar = post_pass(kisitlar, yeni_servisler, parcalar)
    if not yeni_planlar:
        return None
    korunan = [arac for i, arac in enumerate(mevcut_plan) if i not in yikilanlar]

    gun_m = b1.varis_ani.date()
    onceki_dokunus = _tir_dokunus_sayisi([a1, a2], m, gun_m)
    sonraki_dokunus = _tir_dokunus_sayisi(
        [yeni_planlar[0]], m, yeni_planlar[0].bacaklar[0].varis_ani.date(),
    )

    # SLA etkisi: yıkılan araçların (birleştirme + varsa yükseltme) ÖNCEKİ
    # cezaları toplamı ile onarım SONRASI (post_pass'ın merkezi bir vasıtayla
    # gecikmeyi yeniden zamanladığı) ceza toplamı ayrı ayrı raporlanır — slot
    # kazancının SLA'ya ne kadara mal olduğu (ya da fayda sağladığı) görev
    # gereği ayrıca ölçülmeli, yalnız toplam maliyete gömülü kalmamalı.
    yikilan_araclar = [mevcut_plan[i] for i in yikilanlar]
    onceki_sla = sum(
        t.sla_ceza for arac in yikilan_araclar for b in arac.bacaklar for t in b.talepler
    )
    sonraki_sla = sum(
        t.sla_ceza for arac in yeni_planlar for b in arac.bacaklar for t in b.talepler
    )

    hedef = (
        f"zincirleme {x}->{m}->{y}"
        f" (M dokunuş {onceki_dokunus}->{sonraki_dokunus}"
        f", SLA cezası {onceki_sla:.2f}->{sonraki_sla:.2f} TL"
        f"{', +yükseltme' if yukseltme is not None else ''})"
    )
    return korunan + yeni_planlar, hedef


# --------------------------------------------------------------------------
# Ana sürücü
# --------------------------------------------------------------------------

def lns_iyilestir(
    kisitlar: "Kisitlar",
    talep_df: pd.DataFrame,
    tahmin_baslangic: datetime,
    baslangic_plani: list[AracPlan],
    *,
    sure_butce_sn: float = config.LNS_SURE_BUTCE_SN,
    komsuluk_zaman_limit_sn: float = config.LNS_KOMSULUK_ZAMAN_LIMIT_SN,
    rng_seed: int = config.SEED,
) -> LNSSonucu:
    """Böl-onar (LNS) iyileştirme turu (mimari §5.5, issue #22).

    `baslangic_plani` üzerine, süre bütçesi (`sure_butce_sn`) dolana kadar
    rastgele komşuluk denemeleri yapar; yalnız GERÇEK iyileşme VE simülatör
    kapısından geçen adaylar kabul edilir (§5.5). `talep_df`, `kisitlar.talep`
    ile aynı şemada olmalı ve `kisitlar.talep`in KENDİSİ de bu veriyle tutarlı
    olmalı — `simulasyonu_calistir`in SLA kontrolü `kisitlar.talep`i kullanır
    (bkz. `kayan_pencere_coz`/`test_kayan_pencere.py` ile aynı sözleşme).

    Kabul kuralı hiçbir koşuda toplam maliyeti artırmaz: `mevcut_plan` yalnız
    kesin ucuz VE kapıdan geçmiş bir adayla değiştirilir, aksi halde bir önceki
    (zaten geçerli) plan aynen korunur. Bütçe dolduğunda döngü döngünün
    BAŞINDA kontrol edildiği için temiz biter — yarım kalmış bir onarım asla
    `mevcut_plan`a karışmaz (yalnız TAMAMLANMIŞ, kapıdan geçmiş adaylar atanır).
    """
    t0 = time.perf_counter()
    rng = random.Random(rng_seed)

    mevcut_plan: list[AracPlan] = list(baslangic_plani)
    mevcut_maliyet = _plan_maliyeti(mevcut_plan)
    baslangic_maliyet = mevcut_maliyet

    havuz = havuz_uret(kisitlar, talep_df, tahmin_baslangic)
    talep_meta = talep_df.set_index("talep_id")[["cikis", "varis", "tarih", "slot"]].to_dict("index")
    gunler = [tahmin_baslangic.date() + timedelta(days=g) for g in range(GUN_SAYISI)]
    pik_gunler = gunler[:2]  # Pazartesi/Salı (§4.2 — yapısal pik pencere)

    adimlar: list[dict] = []
    adim_no = 0

    while time.perf_counter() - t0 < sure_butce_sn:
        t_adim0 = time.perf_counter()
        komsuluk_tipi = rng.choice(KOMSULUK_TIPLERI)
        onceki_maliyet = mevcut_maliyet
        hata: str | None = None

        try:
            if komsuluk_tipi == "zincirleme":
                repair = _zincirleme_repair(kisitlar, mevcut_plan, talep_meta, rng)
            elif komsuluk_tipi == "bekletme":
                tm = rng.choice(kisitlar.transfer_merkezleri)
                gun = rng.choice(pik_gunler)
                repair = _tm_gun_repair(
                    kisitlar, mevcut_plan, talep_df, havuz,
                    hedef_tmler={tm}, hedef_gunler={gun, gun + timedelta(days=1)},
                    zaman_limit_sn=komsuluk_zaman_limit_sn,
                )
            else:  # "genel"
                tm = rng.choice(kisitlar.transfer_merkezleri)
                gun = rng.choice(gunler)
                repair = _tm_gun_repair(
                    kisitlar, mevcut_plan, talep_df, havuz,
                    hedef_tmler={tm}, hedef_gunler={gun},
                    zaman_limit_sn=komsuluk_zaman_limit_sn,
                )
        except Exception as e:  # noqa: BLE001 — böl-onar denemesi başarısız, tur devam eder
            repair = None
            hata = f"{type(e).__name__}: {e}"

        adim_no += 1

        if repair is None:
            adimlar.append(dict(
                adim_no=adim_no, komsuluk_tipi=komsuluk_tipi, hedef="",
                onceki_maliyet_tl=onceki_maliyet, aday_maliyet_tl=None,
                kabul_edildi=False, sebep=(hata or "uygun aday üretilemedi"),
                sure_sn=time.perf_counter() - t_adim0,
            ))
            continue

        aday_plan, hedef = repair
        aday_maliyet = _plan_maliyeti(aday_plan)

        if aday_maliyet >= onceki_maliyet - 0.01:
            adimlar.append(dict(
                adim_no=adim_no, komsuluk_tipi=komsuluk_tipi, hedef=hedef,
                onceki_maliyet_tl=onceki_maliyet, aday_maliyet_tl=aday_maliyet,
                kabul_edildi=False, sebep="iyileşme yok",
                sure_sn=time.perf_counter() - t_adim0,
            ))
            continue

        try:
            plan_df = plan_yaz(aday_plan)
            simulasyonu_calistir(plan_df, kisitlar)
        except SimulasyonHatasi as e:
            adimlar.append(dict(
                adim_no=adim_no, komsuluk_tipi=komsuluk_tipi, hedef=hedef,
                onceki_maliyet_tl=onceki_maliyet, aday_maliyet_tl=aday_maliyet,
                kabul_edildi=False, sebep=f"simülatör kapısı reddetti: {e}",
                sure_sn=time.perf_counter() - t_adim0,
            ))
            continue

        mevcut_plan = aday_plan
        mevcut_maliyet = aday_maliyet
        adimlar.append(dict(
            adim_no=adim_no, komsuluk_tipi=komsuluk_tipi, hedef=hedef,
            onceki_maliyet_tl=onceki_maliyet, aday_maliyet_tl=aday_maliyet,
            kabul_edildi=True, sebep="kabul edildi",
            sure_sn=time.perf_counter() - t_adim0,
        ))

    adimlar_df = pd.DataFrame(adimlar, columns=[
        "adim_no", "komsuluk_tipi", "hedef", "onceki_maliyet_tl", "aday_maliyet_tl",
        "kabul_edildi", "sebep", "sure_sn",
    ])

    return LNSSonucu(
        arac_planlari=mevcut_plan,
        adimlar=adimlar_df,
        baslangic_maliyet_tl=baslangic_maliyet,
        son_maliyet_tl=mevcut_maliyet,
        toplam_sure_sn=time.perf_counter() - t0,
    )
