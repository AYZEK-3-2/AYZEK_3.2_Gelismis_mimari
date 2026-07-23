# -*- coding: utf-8 -*-
"""Katman 3 kalite kapısı testleri: bağımsız maliyet/SLA hesabı planla uyuşmuyorsa
yakalıyor mu (§6). Bu kapı Katman 3'ün varlık sebebi — MVP'nin self-scoring
hatasını önler — o yüzden uyuşmazlığı yakaladığı doğrudan test edilmeli.
"""
from types import SimpleNamespace

import pandas as pd

from katman0_veri.kisitlar import AracTipi
from katman3_simulator.hesaplamalar import (
    arac_maliyeti_tl,
    kullanim_suresi_dk,
)
from katman3_simulator.simulator import _hesapla_maliyet, _hesapla_sla


def _mock_kisitlar():
    tir = AracTipi(
        ad="Tır", kapasite_desi=22400,
        kiralik_saatlik_tl=291.666667, kiralik_km_tl=13,
        spot_saatlik_tl=487.5, spot_km_tl=25,
    )
    talep = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "toplam_desi": 5000,
    }])
    return SimpleNamespace(
        arac_tipleri={"Tır": tir},
        mesafe_km=lambda c, v: 194,
        seyir_saat=lambda c, v, a: 2.98,
        sla_gun=lambda c, v: 1,
        talep=talep,
    )


def _plan(maliyet, sla_ceza=0.0, varis_tarih="30.06.2026", varis_saat="09:00"):
    return pd.DataFrame([{
        "Araç ID": "V0001", "Araç Tipi": "Spot", "Araç türü": "Tır",
        "Çıkış": "A", "Varış": "B",
        "Çıkış Tarihi": "29.06.2026", "Çıkış Saati": "09:00",
        "Varış Tarihi": varis_tarih, "Varış Saati": varis_saat,
        "Talep ID": "D00001", "Taşınan Desi": 5000,
        "Yolculuk süresi": 179, "Çıkış elleçleme süresi": 50,
        "Varış elleçleme süresi": 50,
        "Toplam maliyet": maliyet, "SLA cezası": sla_ceza,
    }])


def _dogru_maliyet():
    return arac_maliyeti_tl(487.5, 25, kullanim_suresi_dk(5000, 2.98), 194)


# --- maliyet kapısı ----------------------------------------------------------

def test_maliyet_dogruysa_fark_yok():
    k = _mock_kisitlar()
    assert _hesapla_maliyet(_plan(_dogru_maliyet()), k) == []


def test_maliyet_yanlissa_yakalanir():
    k = _mock_kisitlar()
    farklar = _hesapla_maliyet(_plan(_dogru_maliyet() + 1000), k)  # kasıtlı yanlış
    assert len(farklar) == 1
    assert farklar[0]["arac_id"] == "V0001"


# --- SLA kapısı --------------------------------------------------------------

def test_sla_zamaninda_ceza_yok():
    k = _mock_kisitlar()
    # deadline = 29.06 09:00 + 1 gün = 30.06 09:00; varış tam 30.06 09:00
    assert _hesapla_sla(_plan(0.0, varis_saat="09:00"), k) == []


def test_sla_gecikme_yakalanir():
    k = _mock_kisitlar()
    # varış 30.06 12:00 → 3 saat gecikme; plan cezayı 0 yazmış → kapı yakalamalı
    farklar = _hesapla_sla(_plan(0.0, varis_saat="12:00"), k)
    assert len(farklar) == 1
    # 5000 desi × ceil(180dk) 3 saat × 0.4 = 6000 TL beklenen
    assert farklar[0]["sim_ceza"] == 6000.0
