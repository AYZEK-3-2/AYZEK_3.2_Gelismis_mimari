# -*- coding: utf-8 -*-
"""LNS (böl-onar) iyileştirme turu testleri (issue #22, mimari §5.5).

Kabul kriterleri:
1. LNS hiçbir koşuda toplam maliyeti artırmıyor.
2. Zincirleme sonrası slot muhasebesi simülatör sayacıyla birebir.
3. Bütçe dolunca eldeki en iyi plan temiz şekilde döndürülüyor.
"""
import random
from datetime import date, datetime

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.kayan_pencere import _plan_maliyeti, kayan_pencere_coz
from katman2_planlama.lns import (
    _baglantili_yikim_kumesi,
    _en_iyi_yukseltme_adayi,
    _tir_dokunus_sayisi,
    _tm_gun_repair,
    _yikilan_talebi_geri_kazan,
    _zincirleme_ciftleri_bul,
    _zincirleme_repair,
    lns_iyilestir,
)
from katman2_planlama.plan_yazici import AracPlan, BacakAtama, TalepAtama, plan_yaz
from katman2_planlama.servis import Servis, maliyet_hesapla
from katman2_planlama.servis_havuzu import havuz_uret
from katman3_simulator.simulator import SimulasyonHatasi, simulasyonu_calistir

TAHMIN_BASLANGIC = datetime(2026, 6, 29, 9, 0)


class SimpleKisitlar:
    """Test için minimal Kisitlar arayüzü (test_kayan_pencere.py ile aynı desen)."""

    def __init__(self, mesafeler, seyir_saat_deger=2.0, tir_kapasitesi=None,
                 ellecleme_kapasitesi=None, kiralik_hatlar=()):
        cikislar = {c for c, _ in mesafeler}
        varislar = {v for _, v in mesafeler}
        self.transfer_merkezleri = tuple(sorted(cikislar | varislar))
        self.aktif_hatlar = tuple(mesafeler.keys())
        self.arac_tipleri = {
            "Tır": AracTipi("Tır", 20_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyon": AracTipi("Kamyon", 10_000, 150.0, 3.0, 150.0, 3.0),
            "Hafif Kamyon": AracTipi("Hafif Kamyon", 6_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyonet": AracTipi("Kamyonet", 5_000, 80.0, 1.5, 80.0, 1.5),
        }
        self.tir_kapasitesi = tir_kapasitesi or {tm: 5 for tm in self.transfer_merkezleri}
        self.ellecleme_kapasitesi = ellecleme_kapasitesi or {
            tm: 1_000_000.0 for tm in self.transfer_merkezleri
        }
        self.kiralik_hatlar = kiralik_hatlar
        self._mesafe = mesafeler
        self._seyir = seyir_saat_deger

    def hat_var_mi(self, c, v):
        return (c, v) in self._mesafe

    def mesafe_km(self, c, v):
        return self._mesafe[(c, v)]

    def seyir_saat(self, c, v, a):
        return self._seyir

    def sla_gun(self, c, v):
        return 1


class ZincirlemeKisitlar:
    """X->M->Y zincirleme senaryosu için minimal Kisitlar; M'nin tır kapasitesi
    kasıtlı olarak 1 — zincirlemenin gerçek slot kazancını (2 dokunuş -> 1
    dokunuş) sınamak için (§4.1)."""

    def __init__(self):
        self.transfer_merkezleri = ("M", "X", "Y")
        self.arac_tipleri = {
            "Tır": AracTipi("Tır", 20_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyon": AracTipi("Kamyon", 10_000, 150.0, 3.0, 150.0, 3.0),
            "Hafif Kamyon": AracTipi("Hafif Kamyon", 6_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyonet": AracTipi("Kamyonet", 5_000, 80.0, 1.5, 80.0, 1.5),
        }
        self.tir_kapasitesi = {"X": 5, "M": 1, "Y": 5}
        self.ellecleme_kapasitesi = {tm: 1_000_000.0 for tm in self.transfer_merkezleri}
        self.kiralik_hatlar = ()
        self.aktif_hatlar = (("X", "M"), ("M", "Y"))
        self._mesafe = {("X", "M"): 150, ("M", "Y"): 150}

    def hat_var_mi(self, c, v):
        return (c, v) in self._mesafe

    def mesafe_km(self, c, v):
        return self._mesafe[(c, v)]

    def seyir_saat(self, c, v, a):
        return 1.0

    def sla_gun(self, c, v):
        return 3


def _talep_df(gun_sayisi, cikis="A", varis="B", desi=1500.0):
    satirlar = []
    tid = 1
    for gun in range(gun_sayisi):
        tarih = pd.Timestamp(TAHMIN_BASLANGIC.date()) + pd.Timedelta(days=gun)
        for slot in ("09:00", "17:00"):
            satirlar.append({
                "talep_id": f"D{tid:05d}", "tarih": tarih, "cikis": cikis, "varis": varis,
                "slot": slot, "toplam_desi": desi,
            })
            tid += 1
    return pd.DataFrame(satirlar)


def _tir_arac(cikis, varis, cikis_ani, varis_ani, talep_id, desi, maliyet, son_bacak=True):
    """Tek bacaklı, tek talepli AracPlan (test yardımcı fonksiyonu)."""
    return AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=maliyet,
        bacaklar=[BacakAtama(
            cikis=cikis, varis=varis, cikis_ani=cikis_ani, varis_ani=varis_ani,
            seyir_dk=60,
            talepler=[TalepAtama(talep_id=talep_id, desi=desi, son_bacak=son_bacak, sla_ceza=0.0)],
        )],
    )


def _maliyet(kisitlar, cikis, varis, ani, desi):
    return maliyet_hesapla(
        Servis("Tır", False, (cikis, varis), ani), {cikis: desi, varis: desi}, kisitlar,
    ).arac_maliyeti_tl


# --------------------------------------------------------------------------
# Bağlantılı yıkım kümesi + talep geri kazanımı (genel/bekletme komşulukları)
# --------------------------------------------------------------------------

def test_baglantili_yikim_kumesi_paylasilan_kok_talebi_genisletir():
    """D00001'in İKİ parçası da (`son_bacak=True`) birbirinden bağımsız, TAM
    ve nihai teslimlerdir (ör. greedy'nin aynı kök ID'yi ID bölmeden onlarca
    araca "ısırık ısırık" dağıtması, issue #22 canlı testinde bulunan gerçek
    veri deseni) — hiçbiri diğerine dayanan sallanan bir referans taşımaz, o
    yüzden yalnızca birini içeren tohum küme GENİŞLEMEMELİ. Genişleme yalnız
    gerçek bir zincir riski (`son_bacak=False`) olduğunda gerekir (bkz.
    aşağıdaki `..._zincir_riskli_kok_genisletir` testi)."""
    a0 = _tir_arac("A", "B", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 0), "D00001-1", 3000.0, 1000.0)
    a1 = _tir_arac("A", "B", datetime(2026, 6, 29, 11, 0), datetime(2026, 6, 29, 12, 0), "D00001-2", 2000.0, 800.0)
    a2 = _tir_arac("C", "D", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 0), "D00002", 1000.0, 500.0)

    kume = _baglantili_yikim_kumesi([a0, a1, a2], {0})

    assert kume == {0}


def test_baglantili_yikim_kumesi_zincir_riskli_kok_genisletir():
    """a0, D00001'i `son_bacak=False` ile taşıyor — yani GERÇEKTEN başka bir
    araca (a1) devam ediyor. a0'ı a1 olmadan yıkmak, a1'in (hâlâ var olduğu
    varsayılan) sallanan bir referansına yol açar — bu durumda genişleme
    ZORUNLU."""
    a0 = _tir_arac("A", "B", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 0),
                    "D00001", 3000.0, 1000.0, son_bacak=False)
    a1 = _tir_arac("B", "C", datetime(2026, 6, 29, 11, 0), datetime(2026, 6, 29, 12, 0),
                    "D00001", 3000.0, 800.0, son_bacak=True)
    a2 = _tir_arac("X", "Y", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 0), "D00002", 1000.0, 500.0)

    kume = _baglantili_yikim_kumesi([a0, a1, a2], {0})

    assert kume == {0, 1}


def test_yikilan_talebi_geri_kazan_kok_talebi_dogru_toplar():
    talep_df = pd.DataFrame([{
        "talep_id": "D00001", "cikis": "A", "varis": "B",
        "tarih": pd.Timestamp("2026-06-29"), "slot": "09:00", "toplam_desi": 5000.0,
    }])
    a0 = _tir_arac("A", "B", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 0), "D00001-1", 3000.0, 500.0)
    a1 = _tir_arac("A", "B", datetime(2026, 6, 29, 11, 0), datetime(2026, 6, 29, 12, 0), "D00001-2", 2000.0, 400.0)

    yeniden_df = _yikilan_talebi_geri_kazan([a0, a1], {0, 1}, talep_df)

    assert len(yeniden_df) == 1
    row = yeniden_df.iloc[0]
    assert row["talep_id"] == "D00001"
    assert row["toplam_desi"] == pytest.approx(5000.0)
    assert (row["cikis"], row["varis"]) == ("A", "B")


# --------------------------------------------------------------------------
# Genel / bekletme komşuluğu (_tm_gun_repair)
# --------------------------------------------------------------------------

def test_tm_gun_repair_hedefe_dokunan_yoksa_none_doner():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=2)
    kisitlar.talep = talep_df
    baslangic = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=5.0)
    havuz = havuz_uret(kisitlar, talep_df, TAHMIN_BASLANGIC)

    sonuc = _tm_gun_repair(
        kisitlar, baslangic.arac_planlari, talep_df, havuz,
        hedef_tmler={"Hiçbir-TM"}, hedef_gunler={TAHMIN_BASLANGIC.date()},
        zaman_limit_sn=2.0,
    )

    assert sonuc is None


def test_tm_gun_repair_talebi_kaybetmeden_yeniden_kurar_ve_kapidan_gecer():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=2)
    kisitlar.talep = talep_df
    baslangic = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=5.0)
    havuz = havuz_uret(kisitlar, talep_df, TAHMIN_BASLANGIC)

    sonuc = _tm_gun_repair(
        kisitlar, baslangic.arac_planlari, talep_df, havuz,
        hedef_tmler={"A"}, hedef_gunler={TAHMIN_BASLANGIC.date()},
        zaman_limit_sn=3.0,
    )

    assert sonuc is not None
    aday_plan, hedef = sonuc
    assert hedef

    gate = simulasyonu_calistir(plan_yaz(aday_plan), kisitlar)
    assert gate["dogrulama"] == "GECTI"


# --------------------------------------------------------------------------
# Zincirleme komşuluğu (§4.1) — merkezi kabul kriteri: slot muhasebesi
# simülatör sayacıyla birebir.
# --------------------------------------------------------------------------

def test_zincirleme_ciftleri_bul_uygun_cifti_bulur():
    kisitlar = ZincirlemeKisitlar()
    a1 = _tir_arac("X", "M", datetime(2026, 6, 29, 9, 50), datetime(2026, 6, 29, 11, 40),
                    "D00001", 5000.0, _maliyet(kisitlar, "X", "M", datetime(2026, 6, 29, 9, 50), 5000.0))
    a2 = _tir_arac("M", "Y", datetime(2026, 6, 29, 12, 0), datetime(2026, 6, 29, 13, 40),
                    "D00002", 4000.0, _maliyet(kisitlar, "M", "Y", datetime(2026, 6, 29, 12, 0), 4000.0))

    ciftler = _zincirleme_ciftleri_bul([a1, a2])

    assert len(ciftler) == 1
    i1, _, i2, _ = ciftler[0]
    assert (i1, i2) == (0, 1)


def test_zincirleme_gec_kalkan_cift_reddedilir():
    """a2, a1 M'ye varmadan kalkıyorsa (fiziksel olarak imkansız) eşleşmemeli."""
    kisitlar = ZincirlemeKisitlar()
    a1 = _tir_arac("X", "M", datetime(2026, 6, 29, 9, 50), datetime(2026, 6, 29, 11, 40), "D00001", 5000.0, 1000.0)
    a2 = _tir_arac("M", "Y", datetime(2026, 6, 29, 9, 0), datetime(2026, 6, 29, 10, 40), "D00002", 4000.0, 800.0)

    assert _zincirleme_ciftleri_bul([a1, a2]) == []


def _zincirleme_senaryosu():
    kisitlar = ZincirlemeKisitlar()
    talep_df = pd.DataFrame([
        {"talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"), "cikis": "X", "varis": "M",
         "slot": "09:00", "toplam_desi": 5000.0},
        {"talep_id": "D00002", "tarih": pd.Timestamp("2026-06-29"), "cikis": "M", "varis": "Y",
         "slot": "09:00", "toplam_desi": 4000.0},
    ])
    talep_meta = talep_df.set_index("talep_id")[["cikis", "varis", "tarih", "slot"]].to_dict("index")
    a1 = _tir_arac("X", "M", datetime(2026, 6, 29, 9, 50), datetime(2026, 6, 29, 11, 40),
                    "D00001", 5000.0, _maliyet(kisitlar, "X", "M", datetime(2026, 6, 29, 9, 50), 5000.0))
    a2 = _tir_arac("M", "Y", datetime(2026, 6, 29, 12, 0), datetime(2026, 6, 29, 13, 40),
                    "D00002", 4000.0, _maliyet(kisitlar, "M", "Y", datetime(2026, 6, 29, 12, 0), 4000.0))
    return kisitlar, talep_df, talep_meta, a1, a2


def test_zincirleme_repair_ara_tmde_dokunusu_2den_1e_indirir():
    kisitlar, talep_df, talep_meta, a1, a2 = _zincirleme_senaryosu()
    rng = random.Random(0)

    sonuc = _zincirleme_repair(kisitlar, [a1, a2], talep_meta, rng)

    assert sonuc is not None
    aday_plan, hedef = sonuc
    assert len(aday_plan) == 1
    zincir = aday_plan[0]
    assert zincir.arac_tipi == "Tır"
    assert [b.cikis for b in zincir.bacaklar] == ["X", "M"]
    assert [b.varis for b in zincir.bacaklar] == ["M", "Y"]
    # görev gereği slot kazancı VE SLA etkisi ayrı ayrı raporlanmalı
    assert "dokunuş" in hedef
    assert "SLA cezası" in hedef

    gun = zincir.bacaklar[0].varis_ani.date()
    assert _tir_dokunus_sayisi([a1, a2], "M", gun) == 2
    assert _tir_dokunus_sayisi([zincir], "M", gun) == 1

    toplam = sum(t.desi for b in zincir.bacaklar for t in b.talepler)
    assert toplam == pytest.approx(9000.0)


def test_zincirleme_sonrasi_kit_slotlu_tmde_simulator_kapisindan_geciyor():
    """Merkezi kanıt: M'nin tır kapasitesi tam 1. Zincirleme OLMADAN (iki ayrı
    araç, M'de 2 dokunuş) simülatör kapısı Tır slot aşımıyla REDDEDER;
    birleştirilmiş (1 dokunuşluk) haliyle GEÇER. LNS'in kendi slot muhasebesi
    ile simülatörün gerçek kapı kararı böylece birebir örtüşür (issue #22
    kabul kriteri)."""
    kisitlar, talep_df, talep_meta, a1, a2 = _zincirleme_senaryosu()
    kisitlar.talep = talep_df
    rng = random.Random(0)

    with pytest.raises(SimulasyonHatasi, match="Tır slot aşımı"):
        simulasyonu_calistir(plan_yaz([a1, a2]), kisitlar)

    aday_plan, _ = _zincirleme_repair(kisitlar, [a1, a2], talep_meta, rng)
    gate = simulasyonu_calistir(plan_yaz(aday_plan), kisitlar)

    assert gate["dogrulama"] == "GECTI"


def test_en_iyi_yukseltme_adayi_ucuncu_taleple_tiri_yukseltir():
    kisitlar = ZincirlemeKisitlar()
    kisitlar.transfer_merkezleri = kisitlar.transfer_merkezleri + ("Z",)
    kisitlar.tir_kapasitesi["Z"] = 5
    kisitlar.ellecleme_kapasitesi["Z"] = 1_000_000.0
    kisitlar._mesafe[("M", "Z")] = 200

    gun = date(2026, 6, 29)
    kamyon_maliyet = maliyet_hesapla(
        Servis("Kamyon", False, ("M", "Z"), datetime(2026, 6, 29, 12, 0)),
        {"M": 8000.0, "Z": 8000.0}, kisitlar,
    ).arac_maliyeti_tl
    a3 = AracPlan(
        arac_tipi="Kamyon", kiralik=False, toplam_maliyet=kamyon_maliyet,
        bacaklar=[BacakAtama(
            cikis="M", varis="Z", cikis_ani=datetime(2026, 6, 29, 12, 0),
            varis_ani=datetime(2026, 6, 29, 14, 0), seyir_dk=120,
            talepler=[TalepAtama(talep_id="D00003", desi=8000.0, son_bacak=True, sla_ceza=0.0)],
        )],
    )
    talep_meta = {
        "D00003": {"cikis": "M", "varis": "Z", "tarih": pd.Timestamp("2026-06-29"), "slot": "09:00"},
    }

    sonuc = _en_iyi_yukseltme_adayi(kisitlar, [a3], haric=set(), m="M", gun=gun, talep_meta=talep_meta)

    assert sonuc is not None
    idx, servis, parcalar = sonuc
    assert idx == 0
    assert servis.arac_tipi == "Tır"
    assert servis.duraklar == ("M", "Z")
    assert parcalar[0].talep_id == "D00003"
    assert parcalar[0].desi == pytest.approx(8000.0)


def test_en_iyi_yukseltme_adayi_uygun_yoksa_none_doner():
    kisitlar = ZincirlemeKisitlar()
    assert _en_iyi_yukseltme_adayi(
        kisitlar, [], haric=set(), m="M", gun=date(2026, 6, 29), talep_meta={},
    ) is None


# --------------------------------------------------------------------------
# Ana sürücü: kabul kriterleri
# --------------------------------------------------------------------------

def test_lns_hicbir_kosuda_maliyeti_artirmiyor_ve_kapidan_geciyor():
    """Kabul kriteri 1+2: kısa bir bütçeyle çalıştırılan LNS başlangıç
    planından pahalı bir plan asla döndürmez; sonuç simülatörün kuruş
    kapısından geçer; kabul edilen her adım gerçekten daha ucuzdur."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)
    kisitlar.talep = talep_df

    baslangic = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=5.0)
    baslangic_maliyet = _plan_maliyeti(baslangic.arac_planlari)

    sonuc = lns_iyilestir(
        kisitlar, talep_df, TAHMIN_BASLANGIC, baslangic.arac_planlari,
        sure_butce_sn=5.0, komsuluk_zaman_limit_sn=2.0,
    )

    assert sonuc.son_maliyet_tl <= baslangic_maliyet + 0.01
    assert sonuc.son_maliyet_tl == pytest.approx(_plan_maliyeti(sonuc.arac_planlari), abs=0.01)

    gate = simulasyonu_calistir(plan_yaz(sonuc.arac_planlari), kisitlar)
    assert gate["dogrulama"] == "GECTI"

    onceki = baslangic_maliyet
    for _, satir in sonuc.adimlar[sonuc.adimlar["kabul_edildi"]].iterrows():
        assert satir["aday_maliyet_tl"] <= onceki + 0.01
        onceki = satir["aday_maliyet_tl"]


def test_lns_butce_hemen_dolarsa_baslangic_planini_degistirmeden_donuyor():
    """Kabul kriteri 3: bütçe (neredeyse) sıfırsa hiçbir deneme yapılmadan,
    başlangıç planı aynen ve temiz şekilde döner."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=3)
    kisitlar.talep = talep_df
    baslangic = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=5.0)

    sonuc = lns_iyilestir(
        kisitlar, talep_df, TAHMIN_BASLANGIC, baslangic.arac_planlari,
        sure_butce_sn=0.0, komsuluk_zaman_limit_sn=1.0,
    )

    assert sonuc.arac_planlari == baslangic.arac_planlari
    assert sonuc.son_maliyet_tl == pytest.approx(sonuc.baslangic_maliyet_tl, abs=0.01)
    assert len(sonuc.adimlar) == 0


def test_lns_adimlar_raporu_sutunlari():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=3)
    kisitlar.talep = talep_df
    baslangic = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=5.0)

    sonuc = lns_iyilestir(
        kisitlar, talep_df, TAHMIN_BASLANGIC, baslangic.arac_planlari,
        sure_butce_sn=2.0, komsuluk_zaman_limit_sn=1.0,
    )

    beklenen = {
        "adim_no", "komsuluk_tipi", "hedef", "onceki_maliyet_tl", "aday_maliyet_tl",
        "kabul_edildi", "sebep", "sure_sn",
    }
    assert beklenen.issubset(set(sonuc.adimlar.columns))
    assert sonuc.toplam_sure_sn > 0.0
