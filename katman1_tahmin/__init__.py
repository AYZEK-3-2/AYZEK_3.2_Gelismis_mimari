# -*- coding: utf-8 -*-
"""Katman 1: talep tahmini.

(tarih, çıkış TM, varış TM, slot) -> desi. Tek global LightGBM, metrik WAPE.
Bu paket üç parçadan oluşuyor:
  panel.py  — yoğun eğitim paneli + sızıntısız feature'lar (issue #8)
  bolme.py  — walk-forward backtest bölmesi (issue #8)
  <model>   — LightGBM + backtest (issue #9), tahmin yazıcısı (issue #11)
"""
from .bolme import Kat, walk_forward_bol
from .metrik import wape
from .model import KatSonuc, backtest, egit_ve_tahmin, naif_tahmin, rapor_yazdir
from .panel import (
    FEATURE_KOLONLARI,
    SLOTLAR,
    UFUK_GUN,
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
    "UFUK_GUN",
    "walk_forward_bol",
    "Kat",
    "wape",
    "naif_tahmin",
    "egit_ve_tahmin",
    "backtest",
    "rapor_yazdir",
    "KatSonuc",
]


def tahmin_uret(veri):
    # TODO(issue #9, #11): LightGBM eğitimi + backtest + Talep-tahmini.xlsx
    # Panel ve feature altyapısı hazır (issue #8); model henüz yok.
    print("katman1: panel + feature altyapısı hazır (issue #8); model issue #9'da")
    return None
