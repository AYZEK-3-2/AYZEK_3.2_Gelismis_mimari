# -*- coding: utf-8 -*-
"""Katman 0 testleri: yükleme, sanity, değişmezlik, doğrulama kapıları.

Sanity sayıları (69, 7, 289 ...) burada; yükleyicide DEĞİL. Jüri tır
kapasitelerini güncellerse bu testler kırmızıya döner ve haberimiz olur,
ama yükleyici kodu değişmeden yeni dosyayı okumaya devam eder.
"""
import dataclasses

import pandas as pd
import pytest

import config
from katman0_veri import (
    ARAC_ADLARI,
    Kisitlar,
    VeriHatasi,
    dogrula_lojistik,
    dogrula_talep,
    veriyi_yukle,
)


@pytest.fixture(scope="module")
def veri() -> Kisitlar:
    return veriyi_yukle()


# --- yükleme ve tip ----------------------------------------------------------

def test_yukleme_kisitlar_donuyor(veri):
    assert isinstance(veri, Kisitlar)


def test_transfer_merkezleri(veri):
    assert len(veri.transfer_merkezleri) == 18
    assert veri.transfer_merkezleri == tuple(sorted(veri.transfer_merkezleri))  # alfabetik


# --- veriye özgü sanity (mimari §4) -----------------------------------------

def test_toplam_tir_slotu_69(veri):
    assert sum(veri.tir_kapasitesi.values()) == 69


def test_yedi_sifir_tir_tm(veri):
    sifir = {tm for tm, k in veri.tir_kapasitesi.items() if k == 0}
    assert sifir == {"Bilecik", "Denizli", "Isparta", "Karaman", "Kütahya", "Sivas", "Zonguldak"}


def test_kocaeli_varisli_talep_yok(veri):
    assert (veri.talep["varis"] == "Kocaeli").sum() == 0


def test_289_aktif_hat(veri):
    assert len(veri.aktif_hatlar) == 289


def test_306_yonlu_cift(veri):
    assert len(veri._mesafe_km) == 306
    assert len(veri._sla_gun) == 306


def test_talep_satir_sayisi_ve_tarih(veri):
    assert len(veri.talep) == 66024
    assert veri.talep["tarih"].min() == pd.Timestamp("2026-01-01")
    assert veri.talep["tarih"].max() == pd.Timestamp("2026-06-28")
    assert veri.talep["tarih"].dt.date.nunique() == 179


def test_kiralik_14_arac_10_tir(veri):
    assert sum(k.adet for k in veri.kiralik_hatlar) == 14
    assert sum(k.adet for k in veri.kiralik_hatlar if k.arac_turu == "Tır") == 10


def test_arac_parametreleri(veri):
    assert set(veri.arac_tipleri) == set(ARAC_ADLARI)
    tir = veri.arac_tipleri["Tır"]
    assert tir.kapasite_desi == 22400
    assert tir.spot_saatlik_tl == pytest.approx(487.5)
    assert tir.spot_km_tl == 25


# --- slot normalizasyonu (ham '9:00' -> '09:00') ----------------------------

def test_slot_normalize(veri):
    assert set(veri.talep["slot"]) == {"09:00", "17:00"}
    assert set(veri.talep["slot"]) <= set(config.TALEP_SAATLERI)


# --- erişim yardımcıları -----------------------------------------------------

def test_lookuplar(veri):
    assert veri.hat_var_mi("İstanbul", "Yalova")
    assert veri.mesafe_km("İstanbul", "Yalova") == 60
    assert veri.sla_gun("İstanbul", "Yalova") == 1
    assert veri.seyir_saat("İstanbul", "Yalova", "Tır") == pytest.approx(0.92)


# --- değişmezlik -------------------------------------------------------------

def test_frozen_alan_atanamaz(veri):
    with pytest.raises(dataclasses.FrozenInstanceError):
        veri.transfer_merkezleri = ()


def test_sozlukler_salt_okunur(veri):
    with pytest.raises(TypeError):
        veri.tir_kapasitesi["İstanbul"] = 999


# --- doğrulama kapıları (bozuk veri sessiz geçmemeli) -----------------------

def test_eksik_kolon_hata(tmp_path):
    df = pd.read_excel(config.VERI_KLASORU / "tir_kapasiteleri_v2.xlsx").drop(columns=["tir_kapasitesi"])
    # tüm dosyaları kopyala, sadece tır dosyasını boz
    import shutil
    for f in config.VERI_KLASORU.glob("*.xlsx"):
        shutil.copy(f, tmp_path / f.name)
    df.to_excel(tmp_path / "tir_kapasiteleri_v2.xlsx", index=False)
    with pytest.raises(VeriHatasi, match="sütunları beklenenle uyuşmuyor"):
        veriyi_yukle(tmp_path)


def test_eksik_dosya_hata(tmp_path):
    import shutil
    for f in config.VERI_KLASORU.glob("*.xlsx"):
        if f.name != "ellecleme_kapasite.xlsx":
            shutil.copy(f, tmp_path / f.name)
    with pytest.raises(VeriHatasi, match="bulunamadı"):
        veriyi_yukle(tmp_path)


def test_negatif_desi_hata():
    df = pd.DataFrame({
        "tarih": [pd.Timestamp("2026-01-01")],
        "cikis": ["Erzincan"], "varis": ["Mardin"], "talep_id": ["D00001"],
        "toplam_desi": [-5], "talep_tamamlanma_saati": ["9:00"],
    })
    with pytest.raises(VeriHatasi, match="toplam_desi"):
        dogrula_talep(df)


def test_bos_hucre_hata():
    df = pd.DataFrame({
        "tarih": [pd.Timestamp("2026-01-01")],
        "cikis": [None], "varis": ["Mardin"], "talep_id": ["D00001"],
        "toplam_desi": [5], "talep_tamamlanma_saati": ["9:00"],
    })
    with pytest.raises(VeriHatasi, match="boş hücre"):
        dogrula_talep(df)


def test_self_loop_hata():
    df = pd.DataFrame({
        "cikis": ["Mardin"], "varis": ["Mardin"], "mesafe_km": [10],
        "Tir_Suresi_Saat": [1.0], "Kamyon_Suresi_Saat": [1.0],
        "Hafif_Kamyon_Suresi_Saat": [1.0], "Kamyonet_Suresi_Saat": [1.0],
        "hedef_teslim_gun": [1],
    })
    with pytest.raises(VeriHatasi, match="self-loop"):
        dogrula_lojistik(df)
