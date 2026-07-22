# -*- coding: utf-8 -*-
"""Kiralık araç yerleştirici.

14 kiralık araç her gün zorunlu olarak çıkar — 7 gün x 14 araç = 98 servis.
Rota sabit, uğrama yasak, dönüş yok.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.servis import Servis, maliyet_hesapla

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

class KiralikHata(Exception):
    """Kiralık araca yasak işlem yaptırılmaya çalışıldığında atılır."""


class KapasiteDefteri:
    """TM bazında tır slotu ve elleçleme kapasitesi takibi."""

    def __init__(self, kisitlar: "Kisitlar") -> None:
        self.tir_kalan = dict(kisitlar.tir_kapasitesi)
        self.ellecleme_kalan = dict(kisitlar.ellecleme_kapasitesi)

    def tir_slot_dus(self, tm: str, adet: int = 1) -> None:
        if self.tir_kalan.get(tm, 0) < adet:
            raise KiralikHata(f"{tm} TM'sinde yeterli tır slotu yok.")
        self.tir_kalan[tm] -= adet

    def ellecleme_dus(self, tm: str, desi: float) -> None:
        self.ellecleme_kalan[tm] = self.ellecleme_kalan.get(tm, 0) - desi

def kiralik_servisleri_yerlestir(
    kisitlar: "Kisitlar",
    tahmin_df: pd.DataFrame,
    tahmin_baslangic: datetime,
) -> tuple[list[Servis], pd.DataFrame, KapasiteDefteri, float]:
    """
    Zorunlu kiralık servisleri yerleştirir (7 gün × toplam araç adedi).

    Döndürür
    --------
    servisler           : Servis nesneleri
    kalan_talep_df      : spot havuzuna geçen artık talep
    kapasite            : güncellenmiş kapasite defteri
    toplam_maliyet_tl   : sabit kiralık maliyet (TL)
    """
    kapasite = KapasiteDefteri(kisitlar)
    servisler: list[Servis] = []
    kalan_satirlar: list[dict] = []
    toplam_maliyet_tl = 0.0

    # Günlük kapasite rezervasyonu — tır slotu ve elleçleme bir kez düşülür
    for hat in kisitlar.kiralik_hatlar:
        if hat.arac_turu == "Tır":
            kapasite.tir_slot_dus(hat.cikis, hat.adet)
            kapasite.tir_slot_dus(hat.varis, hat.adet)
        gunluk_ellecleme = kisitlar.arac_tipleri[hat.arac_turu].kapasite_desi * hat.adet
        kapasite.ellecleme_dus(hat.cikis, gunluk_ellecleme)
        kapasite.ellecleme_dus(hat.varis, gunluk_ellecleme)

    for gun in range(7):
        tarih = (tahmin_baslangic + timedelta(days=gun)).date()

        for hat in kisitlar.kiralik_hatlar:
            arac_obj = kisitlar.arac_tipleri[hat.arac_turu]
            toplam_kapasite = arac_obj.kapasite_desi * hat.adet

            maske_base = (
                (tahmin_df["tarih"].dt.date == tarih)
                & (tahmin_df["cikis"] == hat.cikis)
                & (tahmin_df["varis"] == hat.varis)
            )
            desi_09 = float(tahmin_df.loc[maske_base & (tahmin_df["slot"] == "09:00"), "toplam_desi"].sum())
            desi_17 = float(tahmin_df.loc[maske_base & (tahmin_df["slot"] == "17:00"), "toplam_desi"].sum())
            baz_saat = 9 if (desi_09 > 0 or desi_17 == 0) else 17

            # Araç yalnızca kendi çıkış slotunun talebini taşır;
            # diğer slotun kargosu o saatte hazır değildir → tamamı spot'a
            if baz_saat == 9:
                yuk_09 = min(desi_09, toplam_kapasite)
                yuk_17 = 0.0
            else:
                yuk_09 = 0.0
                yuk_17 = min(desi_17, toplam_kapasite)
            yuk_desi = yuk_09 + yuk_17
            kalan_09 = desi_09 - yuk_09
            kalan_17 = desi_17 - yuk_17

            ellecleme_dk = math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)
            cikis_ani = datetime.combine(tarih, datetime.min.time().replace(hour=baz_saat)) \
                + timedelta(minutes=ellecleme_dk)

            yuk_per_arac = yuk_desi / hat.adet if hat.adet > 0 else 0.0
            for _ in range(hat.adet):
                servis = Servis(
                    arac_tipi=hat.arac_turu,
                    kiralik=True,
                    duraklar=(hat.cikis, hat.varis),
                    cikis_ani=cikis_ani,
                )
                servisler.append(servis)
                yuk_per_durak = {hat.cikis: yuk_per_arac, hat.varis: yuk_per_arac}
                toplam_maliyet_tl += maliyet_hesapla(servis, yuk_per_durak, kisitlar).arac_maliyeti_tl

            for slot, kalan in (("09:00", kalan_09), ("17:00", kalan_17)):
                if kalan > 0.0:
                    kalan_satirlar.append({
                        "cikis": hat.cikis,
                        "varis": hat.varis,
                        "tarih": tarih,
                        "slot": slot,
                        "kalan_desi": kalan,
                    })

    kalan_talep_df = (
        pd.DataFrame(kalan_satirlar)
        if kalan_satirlar
        else pd.DataFrame(columns=["cikis", "varis", "tarih", "slot", "kalan_desi"])
    )
    return servisler, kalan_talep_df, kapasite, toplam_maliyet_tl
    