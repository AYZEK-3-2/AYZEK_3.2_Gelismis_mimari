# -*- coding: utf-8 -*-
import math
import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.kiralik_placer import KapasiteDefteri
from katman2_planlama.spot_placer import ElleçlemeDefteri, spot_arac_ata

TARIH = date(2026, 6, 29)
TALEP_ANI = datetime(2026, 6, 29, 9)
TAHMIN_BASLANGIC = datetime(2026, 6, 29, 9)


@pytest.fixture
def kisitlar():
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3.0)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    hafif = AracTipi("Hafif Kamyon", 8_000, 0, 0, 60, 1.2)
    kamyonet = AracTipi("Kamyonet", 2_800, 0, 0, 50, 1.0)
    return SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon, "Hafif Kamyon": hafif, "Kamyonet": kamyonet},
        tir_kapasitesi={"A": 0, "B": 0, "C": 0},
        ellecleme_kapasitesi={"A": 999_999, "B": 999_999, "C": 999_999},
        sla_gun=lambda c, v: 1,
        seyir_saat=lambda c, v, a: 10.0,
        mesafe_km=lambda c, v: 800,
    )


@pytest.fixture
def kapasite(kisitlar):
    return KapasiteDefteri(kisitlar)


def _talep(cikis, varis, desi, slot="09:00", tarih=TARIH):
    return {"cikis": cikis, "varis": varis, "tarih": tarih,
            "slot": slot, "kalan_desi": float(desi)}


# --- Unit testler ---

def test_bos_talep(kisitlar, kapasite):
    df = pd.DataFrame(columns=["cikis", "varis", "tarih", "slot", "kalan_desi"])
    servisler, rapor, _ = spot_arac_ata(kisitlar, df, kapasite, TAHMIN_BASLANGIC)
    assert servisler == []
    assert rapor.empty


def test_tam_arac_en_ucuz_tip(kisitlar, kapasite):
    """60.000 desi → 3 tam Kamyon (en ucuz per desi bu fixture'da)."""
    df = pd.DataFrame([_talep("A", "B", 60_000)])
    servisler, _, _ = spot_arac_ata(kisitlar, df, kapasite, TAHMIN_BASLANGIC)
    tipler = [s.arac_tipi for s in servisler]
    assert tipler.count("Kamyon") == 3


def test_artik_yuk_tek_arac(kisitlar, kapasite):
    """21.000 desi = 1 tam Kamyon (20k) + 1 artık araç (1k)."""
    df = pd.DataFrame([_talep("A", "B", 21_000)])
    servisler, _, _ = spot_arac_ata(kisitlar, df, kapasite, TAHMIN_BASLANGIC)
    assert len(servisler) == 2
    assert servisler[0].arac_tipi == "Kamyon"


def test_ellecleme_dolunca_oteleme():
    """Çıkış TM elleçlemesi 0 → yük ertesi güne gitmeli."""
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3.0)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    hafif = AracTipi("Hafif Kamyon", 8_000, 0, 0, 60, 1.2)
    kamyonet = AracTipi("Kamyonet", 2_800, 0, 0, 50, 1.0)
    kis = SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon, "Hafif Kamyon": hafif, "Kamyonet": kamyonet},
        tir_kapasitesi={"A": 0, "B": 0},
        ellecleme_kapasitesi={"A": 0.0, "B": 999_999},  # A tamamen dolu
        sla_gun=lambda c, v: 2,
        seyir_saat=lambda c, v, a: 1.0,
        mesafe_km=lambda c, v: 100,
    )
    kap = KapasiteDefteri(kis)
    df = pd.DataFrame([_talep("A", "B", 20_000)])
    servisler, rapor, _ = spot_arac_ata(kis, df, kap, TAHMIN_BASLANGIC)
    assert len(servisler) == 1
    assert rapor.iloc[0]["tarih"] > TARIH  # ertesi günde çalıştı


def test_hicbir_yuk_disarida_kalmaz():
    """Kapasite sıkışsa bile tüm yük sonunda taşınmalı."""
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3.0)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    hafif = AracTipi("Hafif Kamyon", 8_000, 0, 0, 60, 1.2)
    kamyonet = AracTipi("Kamyonet", 2_800, 0, 0, 50, 1.0)
    kis = SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon, "Hafif Kamyon": hafif, "Kamyonet": kamyonet},
        tir_kapasitesi={"A": 0, "B": 0},
        ellecleme_kapasitesi={"A": 20_000.0, "B": 20_000.0},  # sadece 1 Kamyon/gün
        sla_gun=lambda c, v: 2,
        seyir_saat=lambda c, v, a: 1.0,
        mesafe_km=lambda c, v: 100,
    )
    kap = KapasiteDefteri(kis)
    rows = [_talep("A", "B", 20_000, tarih=TARIH) for _ in range(5)]
    df = pd.DataFrame(rows)
    servisler, rapor, _ = spot_arac_ata(kis, df, kap, TAHMIN_BASLANGIC)
    assert len(servisler) == 5
    assert rapor["yuk_desi"].sum() == pytest.approx(100_000)


def test_kalkis_ani_ellecleme_sonrasi(kisitlar, kapasite):
    """Araç, yükleme elleçlemesi tamamlandıktan sonra hareket etmeli."""
    df = pd.DataFrame([_talep("A", "B", 20_000)])
    servisler, _, _ = spot_arac_ata(kisitlar, df, kapasite, TAHMIN_BASLANGIC)
    assert len(servisler) >= 1
    ell_dk = math.ceil(20_000 * 0.01)  # 200 dk
    beklenen_kalkis = TALEP_ANI + timedelta(minutes=ell_dk)
    assert servisler[0].cikis_ani == beklenen_kalkis


def test_gece_yarisi_ellecleme_bolumu():
    """Gece yarısını aşan elleçleme iki güne oransal bölünmeli."""
    ell = ElleçlemeDefteri({"A": 500_000})
    # 22:00'de başlayan 300 dk'lık elleçleme → 120 dk bugün, 180 dk yarın
    baslangic = datetime(2026, 6, 29, 22, 0)
    desi = 30_000  # 30_000 * 0.01 = 300 dk
    ell.kullan("A", baslangic, desi)
    gun1 = date(2026, 6, 29)
    gun2 = date(2026, 6, 30)
    k1 = ell._kullanim.get(("A", gun1), 0.0)
    k2 = ell._kullanim.get(("A", gun2), 0.0)
    assert k1 + k2 == pytest.approx(desi)
    assert k1 > 0 and k2 > 0


def test_sla_ceza_geciken_yuk():
    """Elleçleme 0 → yük ertele → 1-gün SLA geçirilir → ceza > 0."""
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3.0)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    hafif = AracTipi("Hafif Kamyon", 8_000, 0, 0, 60, 1.2)
    kamyonet = AracTipi("Kamyonet", 2_800, 0, 0, 50, 1.0)
    kis = SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon, "Hafif Kamyon": hafif, "Kamyonet": kamyonet},
        tir_kapasitesi={"A": 0, "B": 0},
        ellecleme_kapasitesi={"A": 0.0, "B": 999_999},
        sla_gun=lambda c, v: 1,  # 1-gün SLA, ertele → gecik
        seyir_saat=lambda c, v, a: 1.0,
        mesafe_km=lambda c, v: 100,
    )
    kap = KapasiteDefteri(kis)
    df = pd.DataFrame([_talep("A", "B", 20_000)])
    _, rapor, _ = spot_arac_ata(kis, df, kap, TAHMIN_BASLANGIC)
    assert rapor["ceza_tl"].sum() > 0


def test_sla_2gun_once_ertelenir():
    """Aynı anda 1-gün ve 2-gün SLA yükü var; kapasite 1 Kamyon → 1-gün SLA günde kalır, 2-gün sonra gider."""
    tir = AracTipi("Tır", 50_000, 0, 0, 150, 3.0)
    kamyon = AracTipi("Kamyon", 20_000, 0, 0, 80, 1.5)
    hafif = AracTipi("Hafif Kamyon", 8_000, 0, 0, 60, 1.2)
    kamyonet = AracTipi("Kamyonet", 2_800, 0, 0, 50, 1.0)
    kis = SimpleNamespace(
        arac_tipleri={"Tır": tir, "Kamyon": kamyon, "Hafif Kamyon": hafif, "Kamyonet": kamyonet},
        tir_kapasitesi={"A": 0, "B": 0, "C": 0},
        ellecleme_kapasitesi={"A": 20_000.0, "B": 999_999, "C": 999_999},
        sla_gun=lambda c, v: 1 if v == "B" else 2,
        seyir_saat=lambda c, v, a: 1.0,
        mesafe_km=lambda c, v: 100,
    )
    kap = KapasiteDefteri(kis)
    df = pd.DataFrame([
        _talep("A", "B", 20_000),  # 1-gün SLA → önce işlenir, günde kalır
        _talep("A", "C", 20_000),  # 2-gün SLA → kapasite bitti, erteler
    ])
    _, rapor, _ = spot_arac_ata(kis, df, kap, TAHMIN_BASLANGIC)
    bugun = rapor[rapor["tarih"] == TARIH]
    yarin = rapor[rapor["tarih"] > TARIH]
    assert bugun[bugun["varis"] == "B"]["yuk_desi"].sum() == pytest.approx(20_000)
    assert yarin[yarin["varis"] == "C"]["yuk_desi"].sum() == pytest.approx(20_000)


# --- Kabul testleri ---

def _bos_tahmin_df():
    return pd.DataFrame({
        "tarih": pd.Series([], dtype="datetime64[ns]"),
        "cikis": pd.Series([], dtype=str),
        "varis": pd.Series([], dtype=str),
        "toplam_desi": pd.Series([], dtype=float),
        "slot": pd.Series([], dtype=str),
    })


def test_kabul_hicbir_yuk_disarida():
    """Gerçek veriyle: tüm kalan desi'nin tamamı taşınmalı."""
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir
    from katman2_planlama.tir_slot_tahsis import tir_slot_tahsis

    kisitlar = veriyi_yukle()
    _, kiralik_kalan, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    # Sentetik yük: ilk 10 hat için 50.000 desi/gün
    satirlar = []
    for gun in range(7):
        tarih = (config.TAHMIN_BASLANGIC + timedelta(days=gun)).date()
        for cikis, varis in list(kisitlar.aktif_hatlar)[:10]:
            satirlar.append({"cikis": cikis, "varis": varis, "tarih": tarih,
                              "slot": "09:00", "kalan_desi": 50_000.0})
    kalan_df = pd.DataFrame(satirlar)
    toplam = kalan_df["kalan_desi"].sum()

    _, rapor, _ = spot_arac_ata(kisitlar, kalan_df, kap, config.TAHMIN_BASLANGIC)
    assert rapor["yuk_desi"].sum() == pytest.approx(toplam, rel=0.01)


def test_kabul_pazartesi_kapasite_asimi_sifir():
    """29.06 Pazartesi: hiçbir TM'nin günlük elleçleme limiti aşılmamalı."""
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir

    kisitlar = veriyi_yukle()
    _, _, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    # Pazartesiyi strese et: her hat için 2× kapasite
    pazartesi = config.TAHMIN_BASLANGIC.date()
    satirlar = []
    for cikis, varis in kisitlar.aktif_hatlar:
        limit = kap.ellecleme_kalan.get(cikis, 0.0)
        satirlar.append({"cikis": cikis, "varis": varis, "tarih": pazartesi,
                          "slot": "09:00", "kalan_desi": max(limit * 2, 20_000.0)})
    kalan_df = pd.DataFrame(satirlar)

    _, rapor, ell = spot_arac_ata(kisitlar, kalan_df, kap, config.TAHMIN_BASLANGIC)

    for tm in kisitlar.transfer_merkezleri:
        # Negatif limit: kiralık zaten kapasiteyi aştı → spot planlayıcının bütçesi 0
        spot_limit = max(0.0, kap.ellecleme_kalan.get(tm, 0.0))
        kullanim = ell._kullanim.get((tm, pazartesi), 0.0)
        assert kullanim <= spot_limit + 1e-3, (
            f"{tm} Pazartesi elleçleme aştı: {kullanim:.0f} > {spot_limit:.0f}"
        )


def test_kabul_sla_ceza_buyuktur_sifir():
    """Pazartesi pik günde en az bir yük gecikir; SLA ceza toplamı sıfırdan büyük olmalı."""
    from katman0_veri.yukleyici import veriyi_yukle
    import config
    from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir

    kisitlar = veriyi_yukle()
    _, _, kap, _ = kiralik_servisleri_yerlestir(
        kisitlar, _bos_tahmin_df(), config.TAHMIN_BASLANGIC
    )
    pazartesi = config.TAHMIN_BASLANGIC.date()
    satirlar = []
    for cikis, varis in kisitlar.aktif_hatlar:
        limit = kap.ellecleme_kalan.get(cikis, 0.0)
        satirlar.append({"cikis": cikis, "varis": varis, "tarih": pazartesi,
                          "slot": "09:00", "kalan_desi": max(limit * 3, 20_000.0)})
    kalan_df = pd.DataFrame(satirlar)

    _, rapor, _ = spot_arac_ata(kisitlar, kalan_df, kap, config.TAHMIN_BASLANGIC)
    assert rapor["ceza_tl"].sum() > 0, "Pik günde SLA cezası bekleniyor"
