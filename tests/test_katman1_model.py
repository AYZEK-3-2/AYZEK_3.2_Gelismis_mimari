# -*- coding: utf-8 -*-
"""Katman 1 model + backtest testleri (issue #9).

Model testleri LightGBM eğittiği için hafif konfig (1 seed, az ağaç) kullanır;
tam konfig raporu `scripts/backtest.py` ile üretilir.
"""
import numpy as np
import pandas as pd
import pytest

from katman0_veri import veriyi_yukle
from katman1_tahmin import (
    backtest,
    egit_ve_tahmin,
    egitim_paneli_kur,
    feature_ekle,
    naif_tahmin,
    wape,
)

HAFIF = dict(seedler=(1,), n_estimators=60)


@pytest.fixture(scope="module")
def veri():
    return veriyi_yukle()


@pytest.fixture(scope="module")
def feat(veri):
    return feature_ekle(egitim_paneli_kur(veri))


# --- WAPE --------------------------------------------------------------------

def test_wape_bilinen_deger():
    # |100-90| + |100-120| = 30; Σ|gerçek| = 200 -> 0.15
    assert wape([100, 100], [90, 120]) == pytest.approx(0.15)


def test_wape_sifir_payda():
    assert wape([0, 0], [5, 3]) == 0.0


def test_wape_mukemmel():
    assert wape([10, 20, 30], [10, 20, 30]) == 0.0


# --- naif taban çizgisi ------------------------------------------------------

def test_naif_lag7_esit(feat):
    test_df = feat[feat["tarih"] >= "2026-06-22"]
    naif = naif_tahmin(test_df)
    beklenen = test_df["lag_7"].fillna(0.0).clip(lower=0).to_numpy()
    np.testing.assert_array_equal(naif, beklenen)


# --- model ------------------------------------------------------------------

def test_egit_ve_tahmin_negatif_yok_ve_boyut(feat):
    train_df = feat[feat["tarih"] <= "2026-06-14"]
    test_df = feat[(feat["tarih"] >= "2026-06-15") & (feat["tarih"] <= "2026-06-21")]
    pred = egit_ve_tahmin(train_df, test_df, **HAFIF)
    assert len(pred) == len(test_df)
    assert (pred >= 0).all()  # zero-floor


def test_egit_ve_tahmin_determinist(feat):
    train_df = feat[feat["tarih"] <= "2026-06-14"]
    test_df = feat[(feat["tarih"] >= "2026-06-15") & (feat["tarih"] <= "2026-06-21")]
    a = egit_ve_tahmin(train_df, test_df, **HAFIF)
    b = egit_ve_tahmin(train_df, test_df, **HAFIF)
    np.testing.assert_array_equal(a, b)  # deterministic=True → bit-eş


# --- backtest ---------------------------------------------------------------

def test_backtest_5_kat_ve_alanlar(veri):
    sonuclar = backtest(veri, **HAFIF)
    assert len(sonuclar) == 5
    assert sonuclar[0].test_araligi == "2026-06-22..2026-06-28"  # kat 0 Haziran sonu
    for s in sonuclar:
        assert s.model_wape >= 0 and s.naif_wape >= 0
        assert set(s.model_wape_slot) == {"09:00", "17:00"}


def test_kat0_tam_konfig_model_naifi_yeniyor(feat):
    """Kabul kriteri: en güncel katta (Haziran sonu) model naifi yener — TAM konfig.

    Hafif konfig (az ağaç/tek seed) naifi yenmeye yetmez; bu kriter tam modelin
    özelliğidir, o yüzden kat 0'ı gerçek parametrelerle eğitip ölçüyoruz.
    """
    train_df = feat[feat["tarih"] <= "2026-06-21"]
    test_df = feat[(feat["tarih"] >= "2026-06-22") & (feat["tarih"] <= "2026-06-28")]
    gercek = test_df["desi"].to_numpy(dtype="float64")
    model_pred = egit_ve_tahmin(train_df, test_df)  # tam konfig (3 seed, 400 ağaç)
    assert wape(gercek, model_pred) < wape(gercek, naif_tahmin(test_df))
