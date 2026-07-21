# -*- coding: utf-8 -*-
"""Tahmin metrikleri.

Baş metrik WAPE (Weighted Absolute Percentage Error): toplam mutlak hata /
toplam gerçek. MAPE bu veride patlıyor (17 desilik satırlar sıfıra yakın payda
üretiyor); WAPE payda olarak toplam desiyi kullandığı için sağlam.
"""
from __future__ import annotations

import numpy as np


def wape(gercek, tahmin) -> float:
    """WAPE = Σ|gerçek - tahmin| / Σ|gerçek|. Payda 0 ise 0 döner."""
    gercek = np.asarray(gercek, dtype="float64")
    tahmin = np.asarray(tahmin, dtype="float64")
    payda = np.abs(gercek).sum()
    if payda == 0:
        return 0.0
    return float(np.abs(gercek - tahmin).sum() / payda)
