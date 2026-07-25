# -*- coding: utf-8 -*-
"""Post-pass testleri (issue #21, mimari §5.4 "kalkışları SLA'ya göre geri çeker")."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.plan_yazici import plan_yaz
from katman2_planlama.post_pass import Parca, bin_pack, post_pass
from katman2_planlama.servis import Servis
from katman3_simulator.simulator import simulasyonu_calistir

DOGUS = datetime(2026, 6, 29, 9, 0)
SLA_BITIS = datetime(2026, 6, 30, 9, 0)


class K:
    def __init__(self):
        self.arac_tipleri = {
            "Kamyon": AracTipi("Kamyon", 10_000, 150.0, 3.0, 150.0, 3.0),
        }
    def mesafe_km(self, c, v):
        return 100
    def seyir_saat(self, c, v, a):
        return 2.0
    def sla_gun(self, c, v):
        return 1


# --------------------------------------------------------------------------
# bin_pack
# --------------------------------------------------------------------------

def test_bin_pack_tam_sigar_bolunmez():
    dagilim = bin_pack([("D1", 500.0)], [(0, 1000.0)])
    assert dagilim == {"D1": [(0, 500.0)]}


def test_bin_pack_ilk_uyani_doldur_tasan_boler():
    dagilim = bin_pack([("D1", 700.0), ("D2", 500.0)], [(0, 600.0), (1, 600.0)])
    assert dagilim["D1"] == [(0, 600.0), (1, 100.0)]
    assert dagilim["D2"] == [(1, 500.0)]


def test_bin_pack_yetersiz_kapasite_hata():
    with pytest.raises(ValueError):
        bin_pack([("D1", 1000.0)], [(0, 500.0)])


# --------------------------------------------------------------------------
# post_pass — gerçek yükle zaman/maliyet düzeltmesi
# --------------------------------------------------------------------------

def test_post_pass_kismi_yukte_ellecleme_kisalir_kalkis_geri_cekilir():
    """3000 desi (tam kapasite 10.000 değil) -> elleçleme ceil(3000*0.01)=30dk;
    kalkış = doğuş(09:00) + 30dk = 09:30 (konservatif tam-kapasite varsayımından
    kısa/erken — §5.4 "geri çekme")."""
    kisitlar = K()
    servis = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 10, 0))
    parca = Parca("D00001", 3000.0, DOGUS, SLA_BITIS, ((0, 0),))

    planlar = post_pass(kisitlar, [servis], [parca])

    assert len(planlar) == 1
    bacak = planlar[0].bacaklar[0]
    assert bacak.cikis_ani == datetime(2026, 6, 29, 9, 30)
    assert bacak.varis_ani == datetime(2026, 6, 29, 12, 0)  # +2h seyir +30dk varış ell.
    assert planlar[0].toplam_maliyet == pytest.approx(150.0 * (30 + 120 + 30) / 60 + 3.0 * 100, abs=0.01)


def test_post_pass_coklu_bacak_zincirleme_hazir_ani_dogru():
    kisitlar = K()
    servis = Servis("Kamyon", False, ("A", "B", "C"), datetime(2026, 6, 29, 10, 0))
    parca = Parca("D00001", 1000.0, DOGUS, SLA_BITIS + timedelta(days=1), ((0, 0), (0, 1)))

    planlar = post_pass(kisitlar, [servis], [parca])
    b0, b1 = planlar[0].bacaklar

    assert b0.cikis_ani == datetime(2026, 6, 29, 9, 10)   # +ceil(1000*0.01)=10dk
    assert b0.varis_ani == datetime(2026, 6, 29, 11, 20)  # +2h +10dk
    assert b1.cikis_ani == b0.varis_ani + timedelta(minutes=10)  # hazır=b0 varış +10dk ell.
    assert b1.varis_ani == b1.cikis_ani + timedelta(hours=2, minutes=10)


def test_post_pass_sla_cezasi_yalniz_son_bacakta():
    kisitlar = K()
    servis = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 10, 0))
    # SLA bitişi çok sıkı (dogus + 1 dk) -> kesin gecikme
    sla_cok_siki = DOGUS + timedelta(minutes=1)
    parca = Parca("D00001", 1000.0, DOGUS, sla_cok_siki, ((0, 0),))

    planlar = post_pass(kisitlar, [servis], [parca])
    talep = planlar[0].bacaklar[0].talepler[0]
    assert talep.son_bacak is True
    assert talep.sla_ceza > 0.0


def test_post_pass_iki_arac_farkli_yuk_bagimsiz_hesaplanir():
    kisitlar = K()
    s1 = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 10, 0))
    s2 = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 15, 0))
    p1 = Parca("D00001", 2000.0, DOGUS, SLA_BITIS, ((0, 0),))
    p2 = Parca("D00002", 5000.0, DOGUS, SLA_BITIS, ((1, 0),))

    planlar = post_pass(kisitlar, [s1, s2], [p1, p2])
    assert len(planlar) == 2
    assert planlar[0].bacaklar[0].talepler[0].desi == 2000.0
    assert planlar[1].bacaklar[0].talepler[0].desi == 5000.0


# --------------------------------------------------------------------------
# Bütünleşik: post_pass -> plan_yaz -> simülatör kapısı
# --------------------------------------------------------------------------

def test_post_pass_plan_yaz_simulator_kapisindan_geciyor():
    kisitlar = K()
    kisitlar.kiralik_hatlar = ()
    kisitlar.ellecleme_kapasitesi = {"A": 1_000_000.0, "B": 1_000_000.0}
    kisitlar.tir_kapasitesi = {"A": 0, "B": 0}
    kisitlar.talep = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "toplam_desi": 3000,
    }])

    servis = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 10, 0))
    parca = Parca("D00001", 3000.0, DOGUS, SLA_BITIS, ((0, 0),))
    planlar = post_pass(kisitlar, [servis], [parca])

    df = plan_yaz(planlar)
    sonuc = simulasyonu_calistir(df, kisitlar)
    assert sonuc["dogrulama"] == "GECTI"
