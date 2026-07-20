# -*- coding: utf-8 -*-
"""Değişmez kısıt nesneleri.

Katman 0'ın ürettiği tek çıktı `Kisitlar`. Tüm sözlükler MappingProxyType
ile salt-okunur; dataclass'lar frozen. Amaç: yükleme bittikten sonra hiçbir
katmanın kısıt verisini —yanlışlıkla bile— değiştirememesi. MVP'de araç
parametreleri config'e elle kopyalanıp kaynakla ayrışmıştı; burada tek kaynak
excel ve nesne bir kez kurulup dondurulur.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import pandas as pd

# Kanonik araç adları (arac_kapasite_maliyet_saat.xlsx satır adlarıyla birebir)
ARAC_ADLARI: tuple[str, ...] = ("Tır", "Kamyon", "Hafif Kamyon", "Kamyonet")


@dataclass(frozen=True)
class AracTipi:
    """Bir araç tipinin kapasite ve maliyet parametreleri (spot + kiralık)."""
    ad: str
    kapasite_desi: int
    kiralik_saatlik_tl: float
    kiralik_km_tl: float
    spot_saatlik_tl: float
    spot_km_tl: float


@dataclass(frozen=True)
class KiralikHat:
    """Zorunlu kiralık sefer: (çıkış, varış) hattında `adet` araç, her gün."""
    cikis: str
    varis: str
    arac_turu: str
    adet: int


@dataclass(frozen=True)
class Kisitlar:
    """Yarışmanın tüm sabit kısıt verisi — değişmez tek kaynak."""
    transfer_merkezleri: tuple[str, ...]              # 18 TM, alfabetik
    aktif_hatlar: tuple[tuple[str, str], ...]         # talepte görülen 289 yönlü hat
    arac_tipleri: Mapping[str, AracTipi]              # ad -> AracTipi
    tir_kapasitesi: Mapping[str, int]                 # TM -> günlük tır slotu
    ellecleme_kapasitesi: Mapping[str, float]         # TM -> günlük desi
    kiralik_hatlar: tuple[KiralikHat, ...]            # zorunlu kiralık seferler
    _mesafe_km: Mapping[tuple[str, str], int]         # (çıkış,varış) -> km
    _sla_gun: Mapping[tuple[str, str], int]           # (çıkış,varış) -> 1|2
    _seyir_saat: Mapping[tuple[str, str, str], float] # (çıkış,varış,araç) -> saat
    # 66.024 satır, normalize slot ('09:00'/'17:00'). NOT: frozen alan yeniden
    # atamayı engeller ama DataFrame içeriği teknik olarak değiştirilebilir;
    # tüketen katman feature üretiminden önce .copy() almalı (tahmin zaten alıyor).
    talep: pd.DataFrame

    # --- erişim yardımcıları -------------------------------------------------
    def hat_var_mi(self, cikis: str, varis: str) -> bool:
        return (cikis, varis) in self._mesafe_km

    def mesafe_km(self, cikis: str, varis: str) -> int:
        return self._mesafe_km[(cikis, varis)]

    def sla_gun(self, cikis: str, varis: str) -> int:
        return self._sla_gun[(cikis, varis)]

    def seyir_saat(self, cikis: str, varis: str, arac_ad: str) -> float:
        return self._seyir_saat[(cikis, varis, arac_ad)]


def _read_only(d: dict) -> Mapping:
    """Sözlüğü salt-okunur görünüme sarar."""
    return MappingProxyType(dict(d))
