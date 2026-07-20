# -*- coding: utf-8 -*-
"""Katman 0: veri ve kısıt çekirdeği.

veri/ altındaki 6 excel'i okur, yükleme anında doğrular ve değiştirilemez
tek bir `Kisitlar` nesnesinde toplar. Tahmin, planlama ve simülatör veriyi
YALNIZ buradan alır; hiçbir katman kendi kodunda excel açmaz. Detay: issue #2.
"""
from .kisitlar import ARAC_ADLARI, AracTipi, Kisitlar, KiralikHat
from .yukleyici import (
    VeriHatasi,
    dogrula_lojistik,
    dogrula_talep,
    dogrula_tm_tutarlilik,
    veriyi_yukle,
)

__all__ = [
    "veriyi_yukle",
    "Kisitlar",
    "AracTipi",
    "KiralikHat",
    "ARAC_ADLARI",
    "VeriHatasi",
    "dogrula_talep",
    "dogrula_lojistik",
    "dogrula_tm_tutarlilik",
]
