# -*- coding: utf-8 -*-
"""Katman 1 panel + feature + bölme testleri (issue #8)."""
import numpy as np
import pandas as pd
import pytest

from katman0_veri import veriyi_yukle
from katman1_tahmin import (
    FEATURE_KOLONLARI,
    egitim_paneli_kur,
    feature_ekle,
    hedef_donustur,
    walk_forward_bol,
)


@pytest.fixture(scope="module")
def veri():
    return veriyi_yukle()


@pytest.fixture(scope="module")
def panel(veri):
    return egitim_paneli_kur(veri)


# --- panel ------------------------------------------------------------------

def test_panel_satir_sayisi(panel):
    # 289 hat × 179 gün × 2 slot
    assert len(panel) == 289 * 179 * 2 == 103462


def test_panel_sutunlar_ve_tip(panel):
    assert list(panel.columns) == ["cikis", "varis", "tarih", "slot", "desi"]
    assert panel["desi"].dtype == "int64"
    assert (panel["desi"] >= 0).all()


def test_sifir_doldurma(panel):
    # ham veri %63,8 dolu → panelde bir hayli sıfır satır olmalı
    assert (panel["desi"] == 0).any()
    assert (panel["desi"] > 0).any()


def test_desi_korunumu(panel, veri):
    # sıfır doldurma ne desi ekler ne kaybeder
    assert panel["desi"].sum() == veri.talep["toplam_desi"].sum()


def test_kocaeli_varis_panelde_yok(panel):
    assert (panel["varis"] == "Kocaeli").sum() == 0


def test_panel_determinist(veri):
    a = egitim_paneli_kur(veri)
    b = egitim_paneli_kur(veri)
    pd.testing.assert_frame_equal(a, b)


# --- feature'lar ------------------------------------------------------------

def test_feature_kolonlari_var(panel):
    f = feature_ekle(panel)
    for kol in FEATURE_KOLONLARI:
        assert kol in f.columns


def test_feature_degerleri(panel):
    f = feature_ekle(panel)
    assert set(f["hafta_gunu"].unique()) <= set(range(7))
    assert set(f["slot_kod"].unique()) == {0, 1}
    assert f["slot_dow"].between(0, 13).all()
    assert f["gun_index"].min() == 0 and f["gun_index"].max() == 178


def test_feature_determinist(panel):
    pd.testing.assert_frame_equal(feature_ekle(panel), feature_ekle(panel))


def test_feature_sizinti_yok(panel):
    """Geleceği bozarsak geçmiş satırların feature'ları DEĞİŞMEMELİ."""
    kesim = pd.Timestamp("2026-05-01")
    bozuk = panel.copy()
    bozuk.loc[bozuk["tarih"] >= kesim, "desi"] *= 1000  # geleceği boz

    f_orij = feature_ekle(panel)
    f_bozuk = feature_ekle(bozuk)
    onceki = f_orij["tarih"] < kesim

    for kol in FEATURE_KOLONLARI:
        if kol == "hat":  # kategori, hedeften bağımsız
            continue
        pd.testing.assert_series_equal(
            f_orij.loc[onceki, kol].reset_index(drop=True),
            f_bozuk.loc[onceki, kol].reset_index(drop=True),
            check_names=False,
            check_categorical=False,
        )


def test_lag_gecmisi_gosteriyor(panel):
    """lag_7 gerçekten 7 gün önceki aynı slot desisi mi?"""
    f = feature_ekle(panel)
    ornek = f[(f["cikis"] == "İstanbul") & (f["varis"] == "Yalova") & (f["slot"] == "17:00")]
    ornek = ornek.sort_values("tarih").reset_index(drop=True)
    # 8. satırın lag_7'si, 1. satırın desi'sine eşit
    assert ornek.loc[7, "lag_7"] == ornek.loc[0, "desi"]


# --- hedef dönüşümü ---------------------------------------------------------

def test_hedef_donustur():
    df = pd.DataFrame({"desi": [0, 9, 99]})
    assert list(hedef_donustur(df, "ham")) == [0.0, 9.0, 99.0]
    np.testing.assert_allclose(hedef_donustur(df, "log1p"), np.log1p([0, 9, 99]))
    with pytest.raises(ValueError):
        hedef_donustur(df, "karekok")


# --- walk-forward bölme -----------------------------------------------------

def test_bolme_5_kat(panel):
    katlar = walk_forward_bol(panel)
    assert len(katlar) == 5
    assert katlar[0].test_bitis == panel["tarih"].max()  # kat 0 en güncel (Haziran sonu)


def test_bolme_bosluk_ve_sira(panel):
    for kat in walk_forward_bol(panel):
        egt = panel.iloc[kat.egitim_idx]["tarih"]
        tst = panel.iloc[kat.test_idx]["tarih"]
        assert egt.max() < tst.min()                       # eğitim testten önce
        assert (kat.test_baslangic - egt.max()).days >= 7  # 7 günlük boşluk
        assert (kat.test_bitis - kat.test_baslangic).days == 6  # 7 günlük pencere
        assert set(kat.egitim_idx) & set(kat.test_idx) == set()  # kesişim yok


def test_bolme_determinist(panel):
    a = walk_forward_bol(panel)
    b = walk_forward_bol(panel)
    for ka, kb in zip(a, b):
        assert np.array_equal(ka.egitim_idx, kb.egitim_idx)
        assert np.array_equal(ka.test_idx, kb.test_idx)
