# -*- coding: utf-8 -*-
"""Servis nesnesi ve maliyet fonksiyonu testleri."""
import pytest
from datetime import datetime

from katman2_planlama.servis import (
    Servis,
    ServisHatasi,
    MaliyetSonuc,
    maliyet_hesapla,
    sla_ceza_hesapla,
)

def test_altin_vektor_500dk():
    """10.000 desi + 5 saat yolculuk = 500 dk kullanım süresi."""

    class FakeKisitlar:
        arac_tipleri = {
            "Kamyon": type("A", (), {
                "kiralik_saatlik_tl": 208.33,
                "kiralik_km_tl": 10.0,
                "spot_saatlik_tl": 318.25,
                "spot_km_tl": 21.0,
            })()
        }

        def seyir_saat(self, cikis, varis, arac):
            return 5.0

        def mesafe_km(self, cikis, varis):
            return 194

    servis = Servis(
        arac_tipi="Kamyon",
        kiralik=False,
        duraklar=("İstanbul", "Ankara"),
        cikis_ani=datetime(2026, 6, 29, 9, 0),
    )

    sonuc = maliyet_hesapla(
        servis=servis,
        yuk_per_durak={"İstanbul": 10000, "Ankara": 10000},
        kisitlar=FakeKisitlar(),
    )

    assert sonuc.kullanim_suresi_dk == 500

def test_altin_vektor_560dk():
    """Aynı sefer + 60 dk araç beklemesi = 560 dk."""

    class FakeKisitlar:
        arac_tipleri = {
            "Kamyon": type("A", (), {
                "kiralik_saatlik_tl": 208.33,
                "kiralik_km_tl": 10.0,
                "spot_saatlik_tl": 318.25,
                "spot_km_tl": 21.0,
            })()
        }

        def seyir_saat(self, cikis, varis, arac):
            return 5.0

        def mesafe_km(self, cikis, varis):
            return 194

    servis = Servis(
        arac_tipi="Kamyon",
        kiralik=False,
        duraklar=("İstanbul", "Ankara"),
        cikis_ani=datetime(2026, 6, 29, 9, 0),
    )

    sonuc = maliyet_hesapla(
        servis=servis,
        yuk_per_durak={"İstanbul": 10000, "Ankara": 10000},
        kisitlar=FakeKisitlar(),
        bekleme_dk=60,
    )

    assert sonuc.kullanim_suresi_dk == 560

def test_talep_bagla_gecerli():
    servis = Servis(
        arac_tipi="Kamyon",
        kiralik=False,
        duraklar=("İstanbul", "Eskişehir", "Ankara"),
        cikis_ani=datetime(2026, 6, 29, 9, 0),
    )
    servis.talep_bagla("İstanbul", "Ankara")  # hata vermemeli


def test_talep_bagla_ters_sira():
    servis = Servis(
        arac_tipi="Kamyon",
        kiralik=False,
        duraklar=("İstanbul", "Eskişehir", "Ankara"),
        cikis_ani=datetime(2026, 6, 29, 9, 0),
    )
    with pytest.raises(ServisHatasi):
        servis.talep_bagla("Ankara", "İstanbul")  # ters sıra, hata vermeli


def test_talep_bagla_rotada_yok():
    servis = Servis(
        arac_tipi="Kamyon",
        kiralik=False,
        duraklar=("İstanbul", "Ankara"),
        cikis_ani=datetime(2026, 6, 29, 9, 0),
    )
    with pytest.raises(ServisHatasi):
        servis.talep_bagla("Bursa", "Ankara")  # Bursa rotada yok, hata vermeli