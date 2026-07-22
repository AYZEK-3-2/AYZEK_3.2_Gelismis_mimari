# -*- coding: utf-8 -*-
"""Servis havuzu üreticisi testleri (issue #18, mimari §5.3)."""
from datetime import datetime

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi, KiralikHat
from katman2_planlama.servis import Servis
from katman2_planlama.servis_havuzu import (
    ServisAdayi,
    _ara_durak_adaylari,
    _baskinlik_buda,
    _kalkis_ani,
    _kucuk_arac_adaylari,
    _rapor_uret,
    _tir_adaylari,
    havuz_uret,
)

BASLANGIC = datetime(2026, 6, 29, 9, 0)


def _arac_tipi(ad, kapasite):
    return AracTipi(
        ad=ad,
        kapasite_desi=kapasite,
        kiralik_saatlik_tl=100.0,
        kiralik_km_tl=2.0,
        spot_saatlik_tl=150.0,
        spot_km_tl=3.0,
    )


@pytest.fixture
def ucgen_kisitlar():
    """A -> B direkt 100 km; A -> M1 -> B sapma tam sınırda (130=1.3x);
    A -> M2 -> B sapma sınırın üstünde (131 > 1.3x); A -> M3 -> B en yakın (120)."""
    mesafeler = {
        ("A", "B"): 100,
        ("A", "M1"): 70, ("M1", "B"): 60,
        ("A", "M2"): 70, ("M2", "B"): 61,
        ("A", "M3"): 60, ("M3", "B"): 60,
    }
    return SimpleNamespaceKisitlar(
        transfer_merkezleri=("A", "B", "M1", "M2", "M3"),
        aktif_hatlar=(("A", "B"),),
        arac_tipleri={
            "Tır": _arac_tipi("Tır", 20000),
            "Kamyon": _arac_tipi("Kamyon", 10000),
            "Hafif Kamyon": _arac_tipi("Hafif Kamyon", 6000),
            "Kamyonet": _arac_tipi("Kamyonet", 5000),
        },
        tir_kapasitesi={"A": 5, "B": 5, "M1": 5, "M2": 5},
        ellecleme_kapasitesi={tm: 1_000_000.0 for tm in ("A", "B", "M1", "M2")},
        kiralik_hatlar=(),
        mesafeler=mesafeler,
        seyir_saat_deger=2.0,
    )


class SimpleNamespaceKisitlar:
    """Test için minimal Kisitlar arayüzü (gerçek dataclass yerine)."""

    def __init__(self, transfer_merkezleri, aktif_hatlar, arac_tipleri,
                 tir_kapasitesi, ellecleme_kapasitesi, kiralik_hatlar,
                 mesafeler, seyir_saat_deger):
        self.transfer_merkezleri = transfer_merkezleri
        self.aktif_hatlar = aktif_hatlar
        self.arac_tipleri = arac_tipleri
        self.tir_kapasitesi = tir_kapasitesi
        self.ellecleme_kapasitesi = ellecleme_kapasitesi
        self.kiralik_hatlar = kiralik_hatlar
        self._mesafeler = mesafeler
        self._seyir_saat_deger = seyir_saat_deger

    def hat_var_mi(self, cikis, varis):
        return (cikis, varis) in self._mesafeler

    def mesafe_km(self, cikis, varis):
        return self._mesafeler[(cikis, varis)]

    def seyir_saat(self, cikis, varis, arac_ad):
        return self._seyir_saat_deger


# --------------------------------------------------------------------------
# Tır adayları — yalnız direkt, sıfır kapasiteli TM'lerde üretilmez (todo 1)
# --------------------------------------------------------------------------

def test_tir_sifir_kapasiteli_tmde_uretilmez():
    kisitlar = SimpleNamespaceKisitlar(
        transfer_merkezleri=("X", "Y"),
        aktif_hatlar=(("X", "Y"),),
        arac_tipleri={"Tır": _arac_tipi("Tır", 20000)},
        tir_kapasitesi={"X": 5, "Y": 0},
        ellecleme_kapasitesi={"X": 1e6, "Y": 1e6},
        kiralik_hatlar=(),
        mesafeler={("X", "Y"): 200},
        seyir_saat_deger=3.0,
    )
    adaylar = _tir_adaylari(kisitlar, "X", "Y", BASLANGIC.date(), tir_serbest=False)
    assert adaylar == []


def test_tir_serbest_anahtari_sifir_kapasiteyi_gecersiz_kilar():
    kisitlar = SimpleNamespaceKisitlar(
        transfer_merkezleri=("X", "Y"),
        aktif_hatlar=(("X", "Y"),),
        arac_tipleri={"Tır": _arac_tipi("Tır", 20000)},
        tir_kapasitesi={"X": 5, "Y": 0},
        ellecleme_kapasitesi={"X": 1e6, "Y": 1e6},
        kiralik_hatlar=(),
        mesafeler={("X", "Y"): 200},
        seyir_saat_deger=3.0,
    )
    adaylar = _tir_adaylari(kisitlar, "X", "Y", BASLANGIC.date(), tir_serbest=True)
    assert len(adaylar) > 0


def test_tir_adaylari_daima_iki_duraklidir(ucgen_kisitlar):
    adaylar = _tir_adaylari(ucgen_kisitlar, "A", "B", BASLANGIC.date(), tir_serbest=False)
    assert adaylar
    assert all(len(a.servis.duraklar) == 2 for a in adaylar)


# --------------------------------------------------------------------------
# Küçük araç adayları — direkt + sapma filtresi (todo 2)
# --------------------------------------------------------------------------

def test_sapma_siniri_tam_sinirda_dahil(ucgen_kisitlar):
    ara = _ara_durak_adaylari(ucgen_kisitlar, "A", "B", sapma_katsayisi=1.3)
    assert "M1" in ara  # 130 km == 1.3 * 100 -> dahil


def test_sapma_siniri_ustunde_haric(ucgen_kisitlar):
    ara = _ara_durak_adaylari(ucgen_kisitlar, "A", "B", sapma_katsayisi=1.3)
    assert "M2" not in ara  # 131 km > 1.3 * 100 -> hariç


def test_ara_durak_max_sayi_en_yakinlari_secer(ucgen_kisitlar):
    # M3=120km (en yakın), M1=130km, M2 sapma dışı zaten. max_sayi=1 -> yalnız M3.
    ara = _ara_durak_adaylari(ucgen_kisitlar, "A", "B", sapma_katsayisi=1.3, max_sayi=1)
    assert ara == ["M3"]


def test_kucuk_arac_max_durak_uc_asilmaz(ucgen_kisitlar):
    adaylar = _kucuk_arac_adaylari(
        ucgen_kisitlar, "A", "B", BASLANGIC.date(),
        sapma_katsayisi=1.3, max_durak=3,
    )
    assert adaylar
    assert all(len(a.servis.duraklar) <= 3 for a in adaylar)


def test_max_durak_iki_ise_ara_durak_uretilmez(ucgen_kisitlar):
    adaylar = _kucuk_arac_adaylari(
        ucgen_kisitlar, "A", "B", BASLANGIC.date(),
        sapma_katsayisi=1.3, max_durak=2,
    )
    assert all(len(a.servis.duraklar) == 2 for a in adaylar)


# --------------------------------------------------------------------------
# Kalkış aday ızgarası — tam kapasite varsayımı (todo 3)
# --------------------------------------------------------------------------

def test_kalkis_ani_tam_kapasite_elleçleme_ekler(ucgen_kisitlar):
    # Kamyon kapasitesi 10.000 desi -> ceil(10000*0.01)=100 dk -> 09:00+100dk=10:40
    ani = _kalkis_ani(BASLANGIC.date(), 9, "Kamyon", ucgen_kisitlar)
    assert ani.hour == 10
    assert ani.minute == 40


def test_kalkis_ani_farkli_arac_tipi_farkli_sure(ucgen_kisitlar):
    tir_ani = _kalkis_ani(BASLANGIC.date(), 9, "Tır", ucgen_kisitlar)  # 20.000 desi -> 200 dk
    kamyonet_ani = _kalkis_ani(BASLANGIC.date(), 9, "Kamyonet", ucgen_kisitlar)  # 5.000 -> 50 dk
    assert tir_ani > kamyonet_ani


# --------------------------------------------------------------------------
# Kiralık servisler — havuza zorunlu girer (todo 4)
# --------------------------------------------------------------------------

def test_kiralik_servisler_zorunlu_olarak_havuzda():
    kisitlar = SimpleNamespaceKisitlar(
        transfer_merkezleri=("Mersin", "Kocaeli"),
        aktif_hatlar=(("Mersin", "Kocaeli"),),
        arac_tipleri={
            "Tır": _arac_tipi("Tır", 20000),
            "Kamyon": _arac_tipi("Kamyon", 10000),
            "Hafif Kamyon": _arac_tipi("Hafif Kamyon", 6000),
            "Kamyonet": _arac_tipi("Kamyonet", 5000),
        },
        tir_kapasitesi={"Mersin": 100, "Kocaeli": 100},
        ellecleme_kapasitesi={"Mersin": 1e6, "Kocaeli": 1e6},
        kiralik_hatlar=(KiralikHat(cikis="Mersin", varis="Kocaeli", arac_turu="Tır", adet=2),),
        mesafeler={("Mersin", "Kocaeli"): 700},
        seyir_saat_deger=5.0,
    )
    bos_df = pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })
    sonuc = havuz_uret(kisitlar, bos_df, BASLANGIC)
    zorunlu_adaylar = [a for a in sonuc.adaylar if a.zorunlu]
    assert len(zorunlu_adaylar) == 7 * 2  # 7 gün x 2 araç
    assert all(a.servis.kiralik for a in zorunlu_adaylar)


# --------------------------------------------------------------------------
# Baskınlık budaması (todo 5)
# --------------------------------------------------------------------------

def _fake_servis(arac_tipi, duraklar, cikis_ani):
    return Servis(arac_tipi=arac_tipi, kiralik=False, duraklar=duraklar, cikis_ani=cikis_ani)


def test_baskinlik_budamasi_ezilen_tipi_eler():
    iyi = ServisAdayi(
        servis=_fake_servis("Kamyon", ("A", "B"), BASLANGIC),
        referans_maliyet_tl=100.0, referans_kullanim_dk=60, kapasite_desi=10000,
        zorunlu=False,
    )
    ezilen = ServisAdayi(
        servis=_fake_servis("Hafif Kamyon", ("A", "B"), BASLANGIC),
        referans_maliyet_tl=150.0, referans_kullanim_dk=60, kapasite_desi=6000,
        zorunlu=False,
    )
    sonuc = _baskinlik_buda([iyi, ezilen])
    assert iyi in sonuc
    assert ezilen not in sonuc


def test_baskinlik_budamasi_zorunlu_adayi_korur():
    iyi = ServisAdayi(
        servis=_fake_servis("Kamyon", ("A", "B"), BASLANGIC),
        referans_maliyet_tl=100.0, referans_kullanim_dk=60, kapasite_desi=10000,
        zorunlu=False,
    )
    zorunlu_ama_ezilen = ServisAdayi(
        servis=_fake_servis("Hafif Kamyon", ("A", "B"), BASLANGIC),
        referans_maliyet_tl=150.0, referans_kullanim_dk=60, kapasite_desi=6000,
        zorunlu=True,
    )
    sonuc = _baskinlik_buda([iyi, zorunlu_ama_ezilen])
    assert zorunlu_ama_ezilen in sonuc


def test_baskinlik_budamasi_farkli_rotayi_karsilastirmiyor():
    a = ServisAdayi(
        servis=_fake_servis("Kamyon", ("A", "B"), BASLANGIC),
        referans_maliyet_tl=100.0, referans_kullanim_dk=60, kapasite_desi=10000,
        zorunlu=False,
    )
    b = ServisAdayi(
        servis=_fake_servis("Hafif Kamyon", ("A", "C"), BASLANGIC),
        referans_maliyet_tl=150.0, referans_kullanim_dk=60, kapasite_desi=6000,
        zorunlu=False,
    )
    sonuc = _baskinlik_buda([a, b])
    assert a in sonuc and b in sonuc  # farklı rota -> karşılaştırılmaz


# --------------------------------------------------------------------------
# Havuz raporu (todo 6)
# --------------------------------------------------------------------------

def test_rapor_toplam_aday_sayisina_esit():
    adaylar = [
        ServisAdayi(
            servis=_fake_servis("Kamyon", ("A", "B"), BASLANGIC),
            referans_maliyet_tl=100.0, referans_kullanim_dk=60, kapasite_desi=10000,
            zorunlu=False,
        ),
        ServisAdayi(
            servis=_fake_servis("Tır", ("A", "B"), BASLANGIC),
            referans_maliyet_tl=90.0, referans_kullanim_dk=50, kapasite_desi=20000,
            zorunlu=False,
        ),
    ]
    rapor = _rapor_uret(adaylar)
    assert rapor["aday_sayisi"].sum() == len(adaylar)


# --------------------------------------------------------------------------
# Kabul kriterleri — gerçek veriyle bütünleşik testler
# --------------------------------------------------------------------------

def _sentetik_tahmin_df(kisitlar, tahmin_baslangic):
    from datetime import timedelta
    satirlar = []
    for gun in range(7):
        tarih = pd.Timestamp((tahmin_baslangic + timedelta(days=gun)).date())
        for cikis, varis in kisitlar.aktif_hatlar:
            for slot in ("09:00", "17:00"):
                satirlar.append({
                    "tarih": tarih, "cikis": cikis, "varis": varis,
                    "toplam_desi": 1000.0, "slot": slot,
                })
    return pd.DataFrame(satirlar)


@pytest.fixture(scope="module")
def gercek_havuz():
    from katman0_veri import veriyi_yukle
    import config

    kisitlar = veriyi_yukle()
    tahmin_df = _sentetik_tahmin_df(kisitlar, config.TAHMIN_BASLANGIC)
    return kisitlar, havuz_uret(kisitlar, tahmin_df, config.TAHMIN_BASLANGIC)


def test_kapsama_her_hat_icin_fizibil_aday_var(gercek_havuz):
    kisitlar, sonuc = gercek_havuz
    servisler = [a.servis for a in sonuc.adaylar]
    for cikis, varis in kisitlar.aktif_hatlar:
        kapsandi = False
        for servis in servisler:
            try:
                servis.talep_bagla(cikis, varis)
                kapsandi = True
                break
            except Exception:
                continue
        assert kapsandi, f"{cikis} -> {varis} için fizibil aday yok"


def test_uretim_suresi_30_saniyenin_altinda(gercek_havuz):
    _, sonuc = gercek_havuz
    assert sonuc.uretim_suresi_sn < 30.0


def test_toplam_aday_sayisi_hedefin_altinda(gercek_havuz):
    _, sonuc = gercek_havuz
    assert len(sonuc.adaylar) < 30_000


def test_gevseme_tir_serbest_havuzu_buyutur():
    from katman0_veri import veriyi_yukle
    import config

    kisitlar = veriyi_yukle()
    tahmin_df = _sentetik_tahmin_df(kisitlar, config.TAHMIN_BASLANGIC)

    sikisik = havuz_uret(kisitlar, tahmin_df, config.TAHMIN_BASLANGIC, tir_serbest=False)
    serbest = havuz_uret(kisitlar, tahmin_df, config.TAHMIN_BASLANGIC, tir_serbest=True)

    tir_sikisik = sum(1 for a in sikisik.adaylar if a.servis.arac_tipi == "Tır" and not a.zorunlu)
    tir_serbest = sum(1 for a in serbest.adaylar if a.servis.arac_tipi == "Tır" and not a.zorunlu)
    assert tir_serbest > tir_sikisik


def test_gevseme_baskinlik_budamasi_kapatilinca_havuz_kucultmuyor():
    from katman0_veri import veriyi_yukle
    import config

    kisitlar = veriyi_yukle()
    tahmin_df = _sentetik_tahmin_df(kisitlar, config.TAHMIN_BASLANGIC)

    budanmis = havuz_uret(kisitlar, tahmin_df, config.TAHMIN_BASLANGIC, baskinlik_budamasi=True)
    budanmamis = havuz_uret(kisitlar, tahmin_df, config.TAHMIN_BASLANGIC, baskinlik_budamasi=False)

    assert len(budanmamis.adaylar) >= len(budanmis.adaylar)
