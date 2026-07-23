# -*- coding: utf-8 -*-
import pytest
import pandas as pd
from datetime import date, timedelta
from types import SimpleNamespace

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.kiralik_placer import KapasiteDefteri
from katman2_planlama.tir_slot_tahsis import tir_slot_tahsis, _MIN_KM

TARIH = date(2026, 6, 29)


@pytest.fixture
def kisitlar():
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    return SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon},
        tir_kapasitesi={"A": 10, "B": 10, "C": 10},
        ellecleme_kapasitesi={"A": 999_999, "B": 999_999, "C": 999_999},
        seyir_saat=lambda c, v, a: 10.0,
        mesafe_km=lambda c, v: 800,
    )


@pytest.fixture
def kapasite(kisitlar):
    return KapasiteDefteri(kisitlar)


def _talep(cikis, varis, desi, slot="09:00", tarih=TARIH):
    return {"cikis": cikis, "varis": varis, "tarih": tarih,
            "slot": slot, "kalan_desi": float(desi)}


def _bos_tahmin_df():
    return pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })


# --- Unit testler ---

def test_bos_talep_bos_cikti(kisitlar, kapasite):
    bos = pd.DataFrame(columns=["cikis", "varis", "tarih", "slot", "kalan_desi"])
    servisler, kalan, _, rapor = tir_slot_tahsis(kisitlar, bos, kapasite)
    assert servisler == []
    assert kalan.empty
    assert rapor.empty


def test_kisa_hatta_tir_atanmaz(kisitlar, kapasite):
    kis = SimpleNamespace(
        arac_tipleri=kisitlar.arac_tipleri,
        tir_kapasitesi=kisitlar.tir_kapasitesi,
        ellecleme_kapasitesi=kisitlar.ellecleme_kapasitesi,
        seyir_saat=kisitlar.seyir_saat,
        mesafe_km=lambda c, v: 90,
    )
    df = pd.DataFrame([_talep("A", "B", 100_000)])
    servisler, _, _, _ = tir_slot_tahsis(kis, df, kapasite)
    assert servisler == []


def test_slot_tukendikce_atama_durur(kisitlar):
    kap = KapasiteDefteri(SimpleNamespace(
        tir_kapasitesi={"A": 2, "B": 10},
        ellecleme_kapasitesi={"A": 999_999, "B": 999_999},
    ))
    df = pd.DataFrame([_talep("A", "B", 250_000)])
    servisler, _, _, _ = tir_slot_tahsis(kisitlar, df, kap)
    assert len(servisler) == 2


def test_tasarruf_sirasi_korunur(kisitlar):
    kis = SimpleNamespace(
        arac_tipleri=kisitlar.arac_tipleri,
        tir_kapasitesi={"A": 1, "B": 10, "C": 10},
        ellecleme_kapasitesi={"A": 999_999, "B": 999_999, "C": 999_999},
        seyir_saat=lambda c, v, a: 10.0 if v == "B" else 7.0,
        mesafe_km=lambda c, v: 800 if v == "B" else 500,
    )
    kap = KapasiteDefteri(kis)
    df = pd.DataFrame([
        _talep("A", "B", 50_000),
        _talep("A", "C", 50_000),
    ])
    servisler, _, _, _ = tir_slot_tahsis(kis, df, kap)
    assert len(servisler) == 1
    assert servisler[0].duraklar == ("A", "B")


def test_kalan_desi_dogru_guncellenir(kisitlar, kapasite):
    df = pd.DataFrame([_talep("A", "B", 100_000)])
    _, kalan, _, _ = tir_slot_tahsis(kisitlar, df, kapasite)
    assert kalan.empty


def test_slot_butcesi_gun_bazli(kisitlar, kapasite):
    # Tır slotu GÜNLÜK sıfırlanır. Aynı hat A->B iki farklı günde, her gün
    # 10'luk slotu aşacak talep (15 tır yükü). Her gün ayrı 10 bütçe olmalı →
    # toplam 20 tır. Eski tek-sayaç kod tüm haftayı 10'la sınırlar (bug).
    tir_kap = kisitlar.arac_tipleri["Tır"].kapasite_desi
    df = pd.DataFrame([
        _talep("A", "B", 15 * tir_kap, tarih=date(2026, 6, 29)),
        _talep("A", "B", 15 * tir_kap, tarih=date(2026, 6, 30)),
    ])
    servisler, _, _, rapor = tir_slot_tahsis(kisitlar, df, kapasite)
    assert len(servisler) == 20  # her gün 10; bug'lı kod 10 verirdi
    assert sorted(rapor["tir_sayisi"].tolist()) == [10, 10]


# --- Kabul testleri ---

def test_kabul_slot_asimi_yok():
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir

    kisitlar = veriyi_yukle()
    _, _, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    satirlar = []
    for gun in range(7):
        tarih = (config.TAHMIN_BASLANGIC + timedelta(days=gun)).date()
        for cikis, varis in kisitlar.aktif_hatlar:
            if kisitlar.mesafe_km(cikis, varis) >= _MIN_KM:
                satirlar.append({"cikis": cikis, "varis": varis, "tarih": tarih,
                                  "slot": "09:00", "kalan_desi": 10_000_000.0})
    _, _, kap_son, _ = tir_slot_tahsis(kisitlar, pd.DataFrame(satirlar), kap)

    for tm, kalan in kap_son.tir_kalan.items():
        assert kalan >= 0, f"{tm}: negatif slot ({kalan})"


def test_kabul_kisa_hat_yok():
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir

    kisitlar = veriyi_yukle()
    _, _, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    satirlar = [{"cikis": c, "varis": v,
                 "tarih": config.TAHMIN_BASLANGIC.date(),
                 "slot": "09:00", "kalan_desi": 50_000.0}
                for c, v in kisitlar.aktif_hatlar]
    servisler, _, _, _ = tir_slot_tahsis(kisitlar, pd.DataFrame(satirlar), kap)

    for s in servisler:
        assert kisitlar.mesafe_km(*s.duraklar) >= _MIN_KM


def test_kabul_gunluk_slot_asilmiyor():
    # Gerçek invariant: hiçbir (TM, gün) o TM'nin GÜNLÜK tır bütçesini aşmamalı.
    # (Eski test tüm haftayı tek-gün bütçesiyle sınırlıyordu — bug'ın kendisiydi.)
    from collections import Counter
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir

    kisitlar = veriyi_yukle()
    _, _, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    gunluk_butce = dict(kap.tir_kalan)  # kiralıktan sonra günlük spot tır slotu

    satirlar = []
    for gun in range(7):
        tarih = (config.TAHMIN_BASLANGIC + timedelta(days=gun)).date()
        for cikis, varis in kisitlar.aktif_hatlar:
            if kisitlar.mesafe_km(cikis, varis) >= _MIN_KM:
                satirlar.append({"cikis": cikis, "varis": varis, "tarih": tarih,
                                  "slot": "09:00", "kalan_desi": 10_000_000.0})
    servisler, _, _, _ = tir_slot_tahsis(kisitlar, pd.DataFrame(satirlar), kap)

    dokunus = Counter()
    for s in servisler:
        gun = s.cikis_ani.date()
        dokunus[(s.duraklar[0], gun)] += 1
        dokunus[(s.duraklar[-1], gun)] += 1
    for (tm, gun), n in dokunus.items():
        assert n <= gunluk_butce[tm], f"{tm} {gun}: {n} > günlük {gunluk_butce[tm]}"

    # Ve per-gün doğru tahsisle toplam, tek-gün bütçesinin çok üstünde olmalı
    assert len(servisler) > sum(gunluk_butce.values()) // 2
