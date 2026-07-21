# -*- coding: utf-8 -*-
"""Katman 1: talep tahmini.

(tarih, çıkış TM, varış TM, slot) -> desi. Tek global LightGBM, metrik WAPE.
Bu paket üç parçadan oluşuyor:
  panel.py  — yoğun eğitim paneli + sızıntısız feature'lar (issue #8)
  bolme.py  — walk-forward backtest bölmesi (issue #8)
  <model>   — LightGBM + backtest (issue #9), tahmin yazıcısı (issue #11)
"""
from .bolme import Kat, walk_forward_bol
from .panel import (
    FEATURE_KOLONLARI,
    SLOTLAR,
    egitim_paneli_kur,
    feature_ekle,
    hedef_donustur,
)

__all__ = [
    "egitim_paneli_kur",
    "feature_ekle",
    "hedef_donustur",
    "FEATURE_KOLONLARI",
    "SLOTLAR",
    "walk_forward_bol",
    "Kat",
]


def tahmin_uret(veri):
    # TODO(issue #9, #11): LightGBM eğitimi + backtest + Talep-tahmini.xlsx
    # Panel ve feature altyapısı hazır (issue #8); model henüz yok.
    print("katman1: panel + feature altyapısı hazır (issue #8); model issue #9'da")
    return None
