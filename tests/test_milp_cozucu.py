# -*- coding: utf-8 -*-
"""Set-partitioning MILP çözücü testleri (issue: mimari §5.4).

Bağımlılıklar: servis havuzu (#18) ve emtia toplulaştırma/graf (#19) — ikisi de mergeli.
Bu dosya yalnızca aradaki MILP'i (`milp_cozucu.milp_coz`) test eder.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.emtia_graf import Emtia, emtia_olustur, graf_kur
from katman2_planlama.milp_cozucu import milp_coz
from katman2_planlama.servis import Servis
from katman2_planlama.servis_havuzu import ServisAdayi

DOGUS_ANI = datetime(2026, 6, 29, 9, 0)
SLA_BITIS = datetime(2026, 6, 30, 9, 0)  # sla_gun=1 -> tam 24 saat


def _arac_tipi(ad, kapasite, spot_saatlik_tl, spot_km_tl=1.0):
    return AracTipi(
        ad=ad,
        kapasite_desi=kapasite,
        kiralik_saatlik_tl=spot_saatlik_tl,
        kiralik_km_tl=spot_km_tl,
        spot_saatlik_tl=spot_saatlik_tl,
        spot_km_tl=spot_km_tl,
    )


class SimpleNamespaceKisitlar:
    """Test için minimal Kisitlar arayüzü (bkz. test_servis_havuzu.py'nin aynı deseni)."""

    def __init__(self, arac_tipleri, ellecleme_kapasitesi, tir_kapasitesi,
                 mesafeler, seyir_saat_deger=2.0):
        self.arac_tipleri = arac_tipleri
        self.ellecleme_kapasitesi = ellecleme_kapasitesi
        self.tir_kapasitesi = tir_kapasitesi
        self._mesafeler = mesafeler
        self._seyir_saat_deger = seyir_saat_deger

    def mesafe_km(self, cikis, varis):
        return self._mesafeler[(cikis, varis)]

    def seyir_saat(self, cikis, varis, arac_ad):
        return self._seyir_saat_deger


def _aday(arac_tipi, kapasite, duraklar=("A", "B"), cikis_ani=DOGUS_ANI, zorunlu=False):
    return ServisAdayi(
        servis=Servis(arac_tipi=arac_tipi, kiralik=False, duraklar=duraklar, cikis_ani=cikis_ani),
        referans_maliyet_tl=0.0, referans_kullanim_dk=0, kapasite_desi=kapasite, zorunlu=zorunlu,
    )


def _tek_emtia_kurulumu(desi=1000.0):
    emtia = Emtia(emtia_id="E00001", varis="B", sla_bitis_ani=SLA_BITIS)
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00001", "cikis": "A",
        "dogus_ani": DOGUS_ANI, "desi": desi,
    }])
    return (emtia,), eslesme


# --------------------------------------------------------------------------
# 1) Mini örnek — 2 TM + 1 gün, elle hesaplanmış optimal maliyetle birebir
# --------------------------------------------------------------------------

def test_mini_ornek_2tm_elle_hesap_ile_birebir():
    # Kamyon: sabit=100*2h + 3*100km=600, değişken=2*100*0.01/60=0.0333/desi
    # Hafif Kamyon: sabit=100*2h... AŞAĞIDA farklı oranlarla ucuz alternatif kuruluyor.
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={
            "Kamyon": _arac_tipi("Kamyon", 10_000, spot_saatlik_tl=150.0, spot_km_tl=3.0),
            "Hafif Kamyon": _arac_tipi("Hafif Kamyon", 6_000, spot_saatlik_tl=100.0, spot_km_tl=2.0),
        },
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 0, "B": 0},
        mesafeler={("A", "B"): 100},
        seyir_saat_deger=2.0,
    )
    kamyon = _aday("Kamyon", 10_000)
    hafif = _aday("Hafif Kamyon", 6_000)
    emtialar, eslesme = _tek_emtia_kurulumu(desi=1000.0)

    _, kenarlar = graf_kur([kamyon, hafif], kisitlar)
    sonuc = milp_coz(kisitlar, (kamyon, hafif), emtialar, eslesme, kenarlar, zaman_limit_sn=10)

    # Elle hesap: Kamyon sabit=150*120/60 + 3*100 = 300+300 = 600 TL
    #             Hafif   sabit=100*120/60 + 2*100 = 200+200 = 400 TL
    # Değişken (1000 desi): Kamyon 2*150*0.01/60*1000=50 TL, Hafif 2*100*0.01/60*1000=33.33 TL
    # Kamyon toplam=650, Hafif toplam=433.33 -> optimal Hafif Kamyon, tek araç (bölmek fazladan sabit maliyet katar)
    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert sonuc.x[hafif] == 1
    assert sonuc.x[kamyon] == 0
    assert sonuc.toplam_maliyet_tl == pytest.approx(1300 / 3, abs=0.5)
    assert sonuc.sla_ceza_tl == pytest.approx(0.0, abs=0.01)
    assert sum(sonuc.kenar_akislari["E00001"].values()) == pytest.approx(1000.0, abs=0.5)


# --------------------------------------------------------------------------
# 2) Birim kısıt testleri
# --------------------------------------------------------------------------

def test_bacak_kapasitesi_yetersizse_x_artiriliyor():
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Kamyonet": _arac_tipi("Kamyonet", 400, spot_saatlik_tl=100.0, spot_km_tl=1.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 0, "B": 0},
        mesafeler={("A", "B"): 50},
    )
    aday = _aday("Kamyonet", 400)
    emtialar, eslesme = _tek_emtia_kurulumu(desi=1000.0)

    _, kenarlar = graf_kur([aday], kisitlar)
    sonuc = milp_coz(kisitlar, (aday,), emtialar, eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    # 1000 desi / 400 kapasite -> en az 3 araç (2x400=800 yetersiz)
    assert sonuc.x[aday] == 3
    assert sum(sonuc.kenar_akislari["E00001"].values()) == pytest.approx(1000.0, abs=0.5)


def test_ellecleme_kapasitesi_asilinca_infeasible():
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Kamyon": _arac_tipi("Kamyon", 10_000, spot_saatlik_tl=100.0, spot_km_tl=1.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 300.0},  # 1000 desi B'de aynı gün sığmıyor
        tir_kapasitesi={"A": 0, "B": 0},
        mesafeler={("A", "B"): 50},
    )
    aday = _aday("Kamyon", 10_000)  # tek kalkış anı -> ertelemek için alternatif yok
    emtialar, eslesme = _tek_emtia_kurulumu(desi=1000.0)

    _, kenarlar = graf_kur([aday], kisitlar)
    sonuc = milp_coz(kisitlar, (aday,), emtialar, eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum == "INFEASIBLE"


def test_ellecleme_gece_yarisini_asan_islem_oransal_bolunuyor():
    """Boşaltma (hedef.an) 23:50'de başlıyor, elleçleme=100dk -> pencere 23:50-01:30.

    B'nin GÜNLÜK kotası her gün aynı (950). Oransal bölme olmasaydı (tüm işlem tek
    güne, 30.06'ya yazılsaydı) 1000 > 950 olur ve INFEASIBLE çıkardı — burada tek
    aday olduğu için kaçış yolu yok. Doğru oranla (%10 29.06'ya=100, %90 30.06'ya=900)
    her iki gün de 950'nin altında kalır ve talep tam karşılanır.
    """
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Kamyon": _arac_tipi("Kamyon", 10_000, spot_saatlik_tl=100.0, spot_km_tl=1.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 950.0},
        tir_kapasitesi={"A": 0, "B": 0},
        mesafeler={("A", "B"): 50},
        seyir_saat_deger=2.0,
    )
    hedef_an = datetime(2026, 6, 29, 23, 50)
    kaynak_an = hedef_an - pd.Timedelta(hours=2)
    aday = _aday("Kamyon", 10_000, cikis_ani=kaynak_an)
    emtialar, eslesme = _tek_emtia_kurulumu(desi=1000.0)
    eslesme.loc[0, "dogus_ani"] = kaynak_an - pd.Timedelta(hours=1)

    _, kenarlar = graf_kur([aday], kisitlar)
    sonuc = milp_coz(kisitlar, (aday,), emtialar, eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    teslim = sum(d for k, d in sonuc.kenar_akislari["E00001"].items() if k.hedef.tm == "B")
    assert teslim == pytest.approx(1000.0, abs=0.5)


def test_tir_slotu_sifirsa_tir_secilmiyor():
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={
            "Tır": _arac_tipi("Tır", 20_000, spot_saatlik_tl=1.0, spot_km_tl=0.1),  # kağıt üstünde en ucuz
            "Kamyon": _arac_tipi("Kamyon", 10_000, spot_saatlik_tl=150.0, spot_km_tl=3.0),
        },
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 5, "B": 0},  # B'de tır slotu yok
        mesafeler={("A", "B"): 100},
    )
    tir = _aday("Tır", 20_000)
    kamyon = _aday("Kamyon", 10_000)
    emtialar, eslesme = _tek_emtia_kurulumu(desi=1000.0)

    _, kenarlar = graf_kur([tir, kamyon], kisitlar)
    sonuc = milp_coz(kisitlar, (tir, kamyon), emtialar, eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert sonuc.x[tir] == 0
    assert sonuc.x[kamyon] >= 1


def test_tir_kotasi_gun_bazinda_sifirlaniyor():
    """A'nın günlük tır kapasitesi=1. İki emtia farklı günlerde doğuyor, her biri kendi
    tırıyla (kapasite=5000, konsolidasyon imkansız) taşınmak zorunda -> A'da toplamda 2
    dokunuş gerekiyor. Kota HAFTALIK/global tek havuz olsaydı ikinci dokunuş sığmaz ve
    INFEASIBLE çıkardı; gün bazında sıfırlanıyorsa ikisi de kendi gününde <=1 kalır.
    """
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Tır": _arac_tipi("Tır", 5_000, spot_saatlik_tl=100.0, spot_km_tl=1.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 1, "B": 1},
        mesafeler={("A", "B"): 100},
        seyir_saat_deger=2.0,
    )
    gun1, gun2 = DOGUS_ANI, DOGUS_ANI + timedelta(days=1)
    tir_gun1 = _aday("Tır", 5_000, cikis_ani=gun1)
    tir_gun2 = _aday("Tır", 5_000, cikis_ani=gun2)
    emtia1 = Emtia("E1", "B", gun1 + timedelta(days=3))
    emtia2 = Emtia("E2", "B", gun2 + timedelta(days=3))
    eslesme = pd.DataFrame([
        {"talep_id": "D1", "emtia_id": "E1", "cikis": "A", "dogus_ani": gun1, "desi": 5000.0},
        {"talep_id": "D2", "emtia_id": "E2", "cikis": "A", "dogus_ani": gun2, "desi": 5000.0},
    ])

    _, kenarlar = graf_kur([tir_gun1, tir_gun2], kisitlar)
    sonuc = milp_coz(kisitlar, (tir_gun1, tir_gun2), (emtia1, emtia2), eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert sonuc.x[tir_gun1] == 1
    assert sonuc.x[tir_gun2] == 1


def test_tir_kotasi_ayni_gun_iki_dokunusu_kaldirmiyor():
    """Aynı senaryo ama iki tır de AYNI gün (yalnızca saat farklı) kalkıyor -> A'da o
    tek gün için 2 dokunuş isteniyor, kapasite=1 -> INFEASIBLE olmalı."""
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Tır": _arac_tipi("Tır", 5_000, spot_saatlik_tl=100.0, spot_km_tl=1.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 1, "B": 1},
        mesafeler={("A", "B"): 100},
        seyir_saat_deger=2.0,
    )
    erken = DOGUS_ANI
    gec = DOGUS_ANI + timedelta(hours=6)  # aynı gün, farklı saat
    tir_a = _aday("Tır", 5_000, cikis_ani=erken)
    tir_b = _aday("Tır", 5_000, cikis_ani=gec)
    emtia1 = Emtia("E1", "B", erken + timedelta(days=3))
    emtia2 = Emtia("E2", "B", gec + timedelta(days=3))
    eslesme = pd.DataFrame([
        {"talep_id": "D1", "emtia_id": "E1", "cikis": "A", "dogus_ani": erken, "desi": 5000.0},
        {"talep_id": "D2", "emtia_id": "E2", "cikis": "A", "dogus_ani": gec, "desi": 5000.0},
    ])

    _, kenarlar = graf_kur([tir_a, tir_b], kisitlar)
    sonuc = milp_coz(kisitlar, (tir_a, tir_b), (emtia1, emtia2), eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum == "INFEASIBLE"


def test_kiralik_zorunlu_aday_x_sabit_bir():
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Tır": _arac_tipi("Tır", 20_000, spot_saatlik_tl=100.0, spot_km_tl=2.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 5, "B": 5},
        mesafeler={("A", "B"): 100},
    )
    kiralik = _aday("Tır", 20_000, zorunlu=True)
    bos_eslesme = pd.DataFrame(columns=["talep_id", "emtia_id", "cikis", "dogus_ani", "desi"])

    _, kenarlar = graf_kur([kiralik], kisitlar)
    sonuc = milp_coz(kisitlar, (kiralik,), (), bos_eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert sonuc.x[kiralik] == 1  # talep olmasa da zorunlu servis çalışır


def test_kiralik_ayni_hatta_birden_fazla_arac_verilen_sayiya_esitleniyor():
    """`kiralik_servisleri_yerlestir` aynı (hat, gün) için `adet` kadar YAPISAL OLARAK ÖZDEŞ
    `Servis` üretir (aynı rota, aynı kalkış anı) -> değerce eşit `ServisAdayi`ler. Bunlar bir
    `dict[ServisAdayi, ...]` anahtarında birbirini ezmemeli; `x[s]` toplamı tam `adet`e eşit
    olmalı (§5.4 kısıt 6: 'x[s] = verilen sayı'), talep sıfır olsa bile.
    """
    kisitlar = SimpleNamespaceKisitlar(
        arac_tipleri={"Tır": _arac_tipi("Tır", 20_000, spot_saatlik_tl=100.0, spot_km_tl=2.0)},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 5, "B": 5},
        mesafeler={("A", "B"): 100},
    )
    adet = 3
    kiralik_adaylar = [_aday("Tır", 20_000, zorunlu=True) for _ in range(adet)]  # değerce özdeş
    bos_eslesme = pd.DataFrame(columns=["talep_id", "emtia_id", "cikis", "dogus_ani", "desi"])

    _, kenarlar = graf_kur(kiralik_adaylar, kisitlar)
    sonuc = milp_coz(kisitlar, tuple(kiralik_adaylar), (), bos_eslesme, kenarlar, zaman_limit_sn=10)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert len(sonuc.x) == 1  # tek eşsiz servis değeri
    assert sum(sonuc.x.values()) == adet  # ama toplam x = verilen sayı


# --------------------------------------------------------------------------
# 3) Bütünleşik — gerçek veri 1 günlük dilim, 60 sn altında fizibil çözüm
# --------------------------------------------------------------------------

def test_gercek_veri_1_gunluk_dilim_60_saniye_altinda_fizibil():
    from katman0_veri import veriyi_yukle
    from katman2_planlama.servis_havuzu import _kucuk_arac_adaylari, _tir_adaylari

    kisitlar = veriyi_yukle()
    ilk_tarih = kisitlar.talep["tarih"].min()
    dilim = kisitlar.talep[kisitlar.talep["tarih"] == ilk_tarih].head(30).copy()

    emtialar, eslesme = emtia_olustur(dilim, kisitlar)

    adaylar: list[ServisAdayi] = []
    for cikis, varis in dilim[["cikis", "varis"]].drop_duplicates().itertuples(index=False):
        adaylar.extend(_tir_adaylari(kisitlar, cikis, varis, ilk_tarih.date(), tir_serbest=False))
        adaylar.extend(_kucuk_arac_adaylari(
            kisitlar, cikis, varis, ilk_tarih.date(),
            sapma_katsayisi=1.3, max_durak=2, ara_durak_max_sayi=None,
        ))

    _, kenarlar = graf_kur(adaylar, kisitlar)
    sonuc = milp_coz(kisitlar, tuple(adaylar), emtialar, eslesme, kenarlar, zaman_limit_sn=60.0)

    assert sonuc.durum in ("OPTIMAL", "FEASIBLE")
    assert sonuc.cozum_suresi_sn < 60.0
