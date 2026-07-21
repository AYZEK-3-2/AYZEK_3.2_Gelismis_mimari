import pytest
from katman3_simulator.hesaplamalar import (
    ellecleme_suresi_dk,
    seyir_suresi_dk,
    kullanim_suresi_dk,
    gece_yarisi_bolme,
    sla_ceza_saat,
)

# Altın vektör 1: 10.000 desi + 5 saat yol = 500 dk
def test_kullanim_suresi_temel():
    assert kullanim_suresi_dk(desi=10_000, seyir_saat=5.0) == 500


# Altın vektör 2: aynı sefer + 1 saat (60 dk) araç beklemesi = 560 dk
def test_kullanim_suresi_bekleme():
    assert kullanim_suresi_dk(desi=10_000, seyir_saat=5.0, bekleme_dk=60) == 560


# Yuvarlama: 0.92 saat seyir -> 56 dk (tavan)
def test_seyir_yuvarlama():
    assert seyir_suresi_dk(0.92) == 56


# Elleçleme: tavan(desi × 0.01)
def test_ellecleme_suresi():
    assert ellecleme_suresi_dk(10_000) == 100
    assert ellecleme_suresi_dk(10_001) == 101
    assert ellecleme_suresi_dk(1) == 1

# Altın vektör 3: 23:30'da 10.000 desi -> 100 dk elleçleme
# 30 dk bugüne (3.000 desi), 70 dk yarına (7.000 desi)
def test_gece_yarisi_bolme():
    bugun, yarin = gece_yarisi_bolme(baslangic_dakika=1410, sure_dk=100)
    assert bugun == pytest.approx(0.3)
    assert yarin == pytest.approx(0.7)


# Gece yarısını aşmayan durum
def test_gece_yarisi_bolme_asmiyor():
    bugun, yarin = gece_yarisi_bolme(baslangic_dakika=600, sure_dk=100)
    assert bugun == 1.0
    assert yarin == 0.0


# Altın vektör 4: SLA gecikme yuvarlaması
def test_sla_ceza_1dk():
    assert sla_ceza_saat(1) == 1


def test_sla_ceza_2saat20dk():
    assert sla_ceza_saat(140) == 3


def test_sla_ceza_tam_saat():
    assert sla_ceza_saat(120) == 2


def test_sla_ceza_sifir():
    assert sla_ceza_saat(0) == 0