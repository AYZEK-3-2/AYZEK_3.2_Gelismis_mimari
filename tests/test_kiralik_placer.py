# -*- coding: utf-8 -*-
import pytest
import pandas as pd
from datetime import datetime, timedelta
from types import SimpleNamespace

from katman0_veri.kisitlar import AracTipi, KiralikHat
from katman2_planlama.kiralik_placer import (
    kiralik_servisleri_yerlestir,
    KapasiteDefteri,
    KiralikHata,
)
from katman2_planlama.servis import ServisHatasi

BASLANGIC = datetime(2026, 6, 29, 9, 0)

@pytest.fixture
def kisitlar():
    tir = AracTipi(
        ad="Tır",
        kapasite_desi=50000,
        kiralik_saatlik_tl=100.0,
        kiralik_km_tl=2.0,
        spot_saatlik_tl=150.0,
        spot_km_tl=3.0,
    )
    hat = KiralikHat(cikis="Mersin", varis="Kocaeli", arac_turu="Tır", adet=12)
    return SimpleNamespace(
        kiralik_hatlar=(hat,),
        arac_tipleri={"Tır": tir},
        tir_kapasitesi={"Mersin": 100, "Kocaeli": 100},
        ellecleme_kapasitesi={"Mersin": 1_000_000.0, "Kocaeli": 1_000_000.0},
        seyir_saat=lambda c, v, a: 5.0,
        mesafe_km=lambda c, v: 700,
    )


@pytest.fixture
def bos_df():
    return pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })

def test_servis_sayisi_mock(kisitlar, bos_df):
    # mock: 1 hat, adet=12 → 7 × 12 = 84
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, bos_df, BASLANGIC)
    assert len(servisler) == 84


def test_kiralik_flag(kisitlar, bos_df):
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, bos_df, BASLANGIC)
    assert all(s.kiralik for s in servisler)


def test_tir_slot_dusuyor(kisitlar, bos_df):
    _, _, kapasite, _ = kiralik_servisleri_yerlestir(kisitlar, bos_df, BASLANGIC)
    assert kapasite.tir_kalan["Mersin"] == 100 - 12
    assert kapasite.tir_kalan["Kocaeli"] == 100 - 12


def test_kalan_talep_var(kisitlar):
    rows = [
        {
            "tarih": pd.Timestamp((BASLANGIC + timedelta(days=g)).date()),
            "cikis": "Mersin",
            "varis": "Kocaeli",
            "toplam_desi": 700_000,
            "slot": "17:00",
        }
        for g in range(7)
    ]
    df = pd.DataFrame(rows)
    _, kalan_df, _, _ = kiralik_servisleri_yerlestir(kisitlar, df, BASLANGIC)
    assert not kalan_df.empty
    assert "slot" in kalan_df.columns
    assert (kalan_df["slot"] == "17:00").all()
    assert (kalan_df["kalan_desi"] == 100_000.0).all()

def test_ugrama_exception(kisitlar, bos_df):
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, bos_df, BASLANGIC)
    servis = servisler[0]  # Mersin -> Kocaeli
    with pytest.raises(ServisHatasi):
        servis.talep_bagla("Eskişehir", "Kocaeli")

def test_09_cikisinda_17_talep_spota_gider(kisitlar):
    # 09:00 + 17:00 talebi birlikte var; araç 09:00'da çıkar → 17:00 kargo spot'a
    df = pd.DataFrame([
        {"tarih": pd.Timestamp(BASLANGIC.date()), "cikis": "Mersin", "varis": "Kocaeli",
         "toplam_desi": 1000, "slot": "09:00"},
        {"tarih": pd.Timestamp(BASLANGIC.date()), "cikis": "Mersin", "varis": "Kocaeli",
         "toplam_desi": 2000, "slot": "17:00"},
    ])
    _, kalan_df, _, _ = kiralik_servisleri_yerlestir(kisitlar, df, BASLANGIC)
    kalan_17 = kalan_df[kalan_df["slot"] == "17:00"]["kalan_desi"].sum()
    kalan_09 = kalan_df[kalan_df["slot"] == "09:00"]["kalan_desi"].sum()
    assert kalan_17 == 2000.0   # 17:00 kargo tamamı spot'a
    assert kalan_09 == 0.0      # 09:00 kargo taşındı (kapasite yeterli)


def test_gercek_servis_sayisi():
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    kisitlar = veriyi_yukle()
    bos = pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, bos, config.TAHMIN_BASLANGIC)
    assert len(servisler) == 98  # 7 gün × 14 araç


def test_gercek_slot_tablosu():
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    kisitlar = veriyi_yukle()
    bos = pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })
    _, _, kapasite, _ = kiralik_servisleri_yerlestir(kisitlar, bos, config.TAHMIN_BASLANGIC)
    beklenen = {
        "Mersin": 11, "Kocaeli": 9, "Eskişehir": 8,
        "Manisa": 3, "İstanbul": 2, "Yalova": 1,
        "Balıkesir": 0, "Tekirdağ": 0,
    }
    for tm, kalan in beklenen.items():
        assert kapasite.tir_kalan[tm] == kalan, f"{tm}: beklenen {kalan}, gelen {kapasite.tir_kalan[tm]}"


def test_tir_slot_asimi_exception(kisitlar):
    kapasite = KapasiteDefteri(kisitlar)
    kapasite.tir_slot_dus("Mersin", 100)  # tam tüket
    with pytest.raises(KiralikHata):
        kapasite.tir_slot_dus("Mersin", 1)  # bir fazlası exception atmalı


def test_bos_sefer_maliyet_odenir(kisitlar, bos_df):
    _, _, _, maliyet = kiralik_servisleri_yerlestir(kisitlar, bos_df, BASLANGIC)
    assert maliyet > 0  # talep yoksa da seyir+km maliyeti işlenir


def test_cikis_saati_09_talep_varsa(kisitlar):
    df = pd.DataFrame([{
        "tarih": pd.Timestamp(BASLANGIC.date()),
        "cikis": "Mersin", "varis": "Kocaeli",
        "toplam_desi": 1000, "slot": "09:00",
    }])
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, df, BASLANGIC)
    assert servisler[0].cikis_ani.hour == 9


def test_cikis_saati_17_sadece_17_talep_varsa(kisitlar):
    df = pd.DataFrame([{
        "tarih": pd.Timestamp(BASLANGIC.date()),
        "cikis": "Mersin", "varis": "Kocaeli",
        "toplam_desi": 1000, "slot": "17:00",
    }])
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, df, BASLANGIC)
    assert servisler[0].cikis_ani.hour == 17


def test_cikis_saati_arac_basina_ellecleme(kisitlar):
    # Hat adet=12; 09:00'da 24.000 desi => araç başına 2.000 => elleçleme
    # ceil(2000*0.01)=20 dk => çıkış 09:20. Toplam yük (24.000) üzerinden
    # hesaplansaydı 240 dk (13:00) çıkardı — bu yanlış ve maliyetle çelişirdi.
    df = pd.DataFrame([{
        "tarih": pd.Timestamp(BASLANGIC.date()),
        "cikis": "Mersin", "varis": "Kocaeli",
        "toplam_desi": 24000, "slot": "09:00",
    }])
    servisler, _, _, _ = kiralik_servisleri_yerlestir(kisitlar, df, BASLANGIC)
    assert servisler[0].cikis_ani.hour == 9
    assert servisler[0].cikis_ani.minute == 20