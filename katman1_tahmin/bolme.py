# -*- coding: utf-8 -*-
"""Walk-forward backtest bölmesi (sızıntı boşluklu).

Ufuk 7 gün olduğu için eğitim ile test arasına **7 günlük boşluk** konur
(mimari §7): test penceresinin hemen öncesindeki günlerle eğitip o pencereyi
tahmin etmek, gerçek teslim koşulunu (7 gün ileriyi görmeden) taklit etmez.
Son kat mutlaka en güncel penceredir (Haziran sonu) — trend Ocak→Haziran
%75 arttığı için eski katlarda iyi görünen model güncelde kötü olabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Kat:
    """Bir backtest katı: eğitim/test satır indeksleri + tarih sınırları."""
    kat_no: int
    egitim_idx: np.ndarray
    test_idx: np.ndarray
    egitim_bitis: pd.Timestamp
    test_baslangic: pd.Timestamp
    test_bitis: pd.Timestamp


def walk_forward_bol(
    panel: pd.DataFrame,
    kat_sayisi: int = 5,
    test_gun: int = 7,
    bosluk_gun: int = 7,
) -> list[Kat]:
    """En güncelden geriye doğru `kat_sayisi` kat üretir.

    Kat 0 en güncel test penceresi (veri sonu). Her kat için:
      test  = [test_baslangic, test_bitis]  (test_gun uzunluğunda)
      boşluk = test_baslangic'tan önceki `bosluk_gun` gün (eğitime girmez)
      eğitim = boşluğun da öncesindeki tüm günler (genişleyen pencere)
    """
    tarih = panel["tarih"]
    son = tarih.max()

    katlar: list[Kat] = []
    for k in range(kat_sayisi):
        test_bitis = son - pd.Timedelta(days=k * test_gun)
        test_baslangic = test_bitis - pd.Timedelta(days=test_gun - 1)
        egitim_bitis = test_baslangic - pd.Timedelta(days=bosluk_gun)  # boşluk

        egitim_mask = tarih <= egitim_bitis
        test_mask = (tarih >= test_baslangic) & (tarih <= test_bitis)

        if not egitim_mask.any() or not test_mask.any():
            break  # veri başına dayandık, daha fazla kat üretme

        katlar.append(
            Kat(
                kat_no=k,
                egitim_idx=np.flatnonzero(egitim_mask.to_numpy()),
                test_idx=np.flatnonzero(test_mask.to_numpy()),
                egitim_bitis=egitim_bitis,
                test_baslangic=test_baslangic,
                test_bitis=test_bitis,
            )
        )

    return katlar
