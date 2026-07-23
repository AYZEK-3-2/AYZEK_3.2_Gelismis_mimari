import pytest
from katman3_simulator.kapasite import KapasiteDefter


def test_ellecleme_kapasite_altinda():
    """Kapasite altında — ihlal yok."""
    defter = KapasiteDefter(
        ellecleme_kapasiteleri={"İstanbul": 400_000},
        tir_kapasiteleri={"İstanbul": 10},
    )
    defter.ellecleme_ekle("İstanbul", "2026-06-29", 300_000)
    assert defter.dogrula() == []


def test_ellecleme_kapasite_asimi():
    """Kapasite aşımı — ihlal dönmeli."""
    defter = KapasiteDefter(
        ellecleme_kapasiteleri={"İstanbul": 400_000},
        tir_kapasiteleri={"İstanbul": 10},
    )
    defter.ellecleme_ekle("İstanbul", "2026-06-29", 500_000)
    ihlaller = defter.dogrula()
    assert len(ihlaller) == 1
    assert "Elleçleme aşımı" in ihlaller[0]


def test_tir_slot_asimi():
    """Tır slotu aşımı — ihlal dönmeli."""
    defter = KapasiteDefter(
        ellecleme_kapasiteleri={"Kütahya": 100_000},
        tir_kapasiteleri={"Kütahya": 0},
    )
    defter.tir_dokunusu_ekle("Kütahya", "2026-06-29")
    ihlaller = defter.dogrula()
    assert len(ihlaller) == 1
    assert "Tır slot aşımı" in ihlaller[0]


def test_tir_sifir_kapasiteye_giremez():
    """7 TM'de tır kapasitesi 0 — tek dokunuş bile ihlal."""
    sifir_tmler = ["Kütahya", "Isparta", "Bilecik", "Zonguldak", "Karaman", "Sivas", "Denizli"]
    for tm in sifir_tmler:
        defter = KapasiteDefter(
            ellecleme_kapasiteleri={tm: 100_000},
            tir_kapasiteleri={tm: 0},
        )
        defter.tir_dokunusu_ekle(tm, "2026-06-29")
        ihlaller = defter.dogrula()
        assert len(ihlaller) == 1, f"{tm} için ihlal bekleniyordu"


def test_konsolidasyon_cift_ellecleme():
    """Konsolidasyon: indir + yükle = kapasiteden x+y düşer."""
    defter = KapasiteDefter(
        ellecleme_kapasiteleri={"Eskişehir": 15_000},
        tir_kapasiteleri={"Eskişehir": 10},
    )
    # 10.000 indir + 5.000 yükle = 15.000
    defter.ellecleme_ekle("Eskişehir", "2026-06-29", 10_000)
    defter.ellecleme_ekle("Eskişehir", "2026-06-29", 5_000)
    assert defter.dogrula() == []  # tam sınırda, ihlal yok

    # 1 desi daha eklersen aşar
    defter.ellecleme_ekle("Eskişehir", "2026-06-29", 1)
    ihlaller = defter.dogrula()
    assert len(ihlaller) == 1


def test_farkli_gunler_ayri():
    """Pazartesi ve Salı ayrı kotalar."""
    defter = KapasiteDefter(
        ellecleme_kapasiteleri={"İstanbul": 400_000},
        tir_kapasiteleri={"İstanbul": 10},
    )
    defter.ellecleme_ekle("İstanbul", "2026-06-29", 350_000)
    defter.ellecleme_ekle("İstanbul", "2026-06-30", 350_000)
    assert defter.dogrula() == []  # her gün kendi içinde sınırda