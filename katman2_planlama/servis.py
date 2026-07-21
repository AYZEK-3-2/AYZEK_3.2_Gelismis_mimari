# -*- coding: utf-8 -*-
"""Servis nesnesi ve maliyet fonksiyonu çekirdeği."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

class ServisHatasi(Exception):
    """Geçersiz talep bağlama veya hatalı rota."""

@dataclass(frozen=True)
class Servis:
    arac_tipi: str
    kiralik: bool
    duraklar: tuple[str, ...]
    cikis_ani: datetime

    def __post_init__(self) -> None:
        if len(self.duraklar) < 2:
            raise ServisHatasi("Servis en az 2 durak gerektirir.")
        if len(set(self.duraklar)) != len(self.duraklar):
            raise ServisHatasi("Servis durakları tekrar içeriyor.")

    def bacaklar(self) -> list[tuple[str, str]]:
        return [
            (self.duraklar[i], self.duraklar[i + 1])
            for i in range(len(self.duraklar) - 1)
        ]

    def talep_bagla(self, cikis: str, varis: str) -> None:
        if cikis not in self.duraklar:
            raise ServisHatasi(f"'{cikis}' bu serviste yok: {self.duraklar}")
        if varis not in self.duraklar:
            raise ServisHatasi(f"'{varis}' bu serviste yok: {self.duraklar}")
        if self.duraklar.index(cikis) >= self.duraklar.index(varis):
            raise ServisHatasi(
                f"'{cikis}' '{varis}'den önce gelmiyor: {self.duraklar}"
            )

    def ziyaret_ani(self, tm: str, kisitlar: "Kisitlar") -> datetime:
        from datetime import timedelta
        if tm not in self.duraklar:
            raise ServisHatasi(f"'{tm}' bu serviste yok: {self.duraklar}")
        ani = self.cikis_ani
        for cikis_tm, varis_tm in self.bacaklar():
            if cikis_tm == tm:
                return ani
            ani += timedelta(minutes=_seyir_dk(
                kisitlar.seyir_saat(cikis_tm, varis_tm, self.arac_tipi)
            ))
        return ani        


def _seyir_dk(seyir_saat: float) -> int:
    return math.ceil(seyir_saat * 60)


def _ellecleme_dk(yuk_desi: float) -> int:
    return math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)


def _gecikme_saat_tavan(gecikme_dk: float) -> int:
    return math.ceil(gecikme_dk / 60)

@dataclass(frozen=True)
class MaliyetSonuc:
    kullanim_suresi_dk: int
    arac_maliyeti_tl: float
    toplam_km: int

def maliyet_hesapla(
    servis: Servis,
    yuk_per_durak: dict[str, float],
    kisitlar: "Kisitlar",
    bekleme_dk: int = 0,
) -> MaliyetSonuc:
    arac = kisitlar.arac_tipleri[servis.arac_tipi]
    bacaklar = servis.bacaklar()

    sur_dk = _ellecleme_dk(yuk_per_durak.get(servis.duraklar[0], 0.0)) 
    sur_dk += bekleme_dk

    toplam_km = 0
    for i, (cikis_tm, varis_tm) in enumerate(bacaklar):
        sur_dk += _seyir_dk(kisitlar.seyir_saat(cikis_tm, varis_tm, servis.arac_tipi))
        toplam_km += kisitlar.mesafe_km(cikis_tm, varis_tm)
        if i < len(bacaklar) - 1:
            sur_dk += _ellecleme_dk(yuk_per_durak.get(varis_tm, 0.0))

    sur_dk += _ellecleme_dk(yuk_per_durak.get(servis.duraklar[-1], 0.0))

    saatlik = arac.kiralik_saatlik_tl if servis.kiralik else arac.spot_saatlik_tl
    km_ucret = arac.kiralik_km_tl if servis.kiralik else arac.spot_km_tl
    arac_maliyeti = saatlik * sur_dk / 60.0 + km_ucret * toplam_km

    return MaliyetSonuc(
        kullanim_suresi_dk=sur_dk,
        arac_maliyeti_tl=arac_maliyeti,
        toplam_km=toplam_km,
    ) 

def sla_ceza_hesapla(
    teslim_ani: datetime,
    sla_bitis_ani: datetime,
    yuk_desi: float,
) -> float:
    if teslim_ani <= sla_bitis_ani:
        return 0.0
    gecikme_dk = (teslim_ani - sla_bitis_ani).total_seconds() / 60.0
    gecikme_saat = _gecikme_saat_tavan(gecikme_dk)
    return round(yuk_desi * gecikme_saat * config.SLA_CEZA_TL_PER_DESI_SAAT, 2)
