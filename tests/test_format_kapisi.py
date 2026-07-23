import pandas as pd
import pytest
from katman3_simulator.format_kapisi import (
    dogrula_plan_formati,
    dogrula_muhasebe,
    dogrula_talep_butunlugu,
)
from katman3_simulator.simulator import SimulasyonHatasi


def sahte_plan():
    return pd.DataFrame({
        "Araç ID": ["V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot"],
        "Araç türü": ["Tır", "Tır"],
        "Çıkış": ["İstanbul", "İstanbul"],
        "Varış": ["Yalova", "Yalova"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "09:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:30", "10:30"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        "Çıkış elleçleme süresi": [80, 80],
        "Varış elleçleme süresi": [80, 80],
        "Toplam maliyet": [5000.0, 0.0],
        "SLA cezası": [0.0, 0.0],
    })


# --- Format kontrolleri ---

def test_gecerli_format():
    df = sahte_plan()
    dogrula_plan_formati(df)  # hata yok


def test_yanlis_saat_formati():
    df = sahte_plan()
    df.loc[0, "Çıkış Saati"] = "09:00:00"  # SS:DD:ss yanlış
    with pytest.raises(SimulasyonHatasi, match="SS:DD olmalı"):
        dogrula_plan_formati(df)


def test_gecersiz_arac_tipi():
    df = sahte_plan()
    df.loc[0, "Araç Tipi"] = "Özel"
    with pytest.raises(SimulasyonHatasi, match="Geçersiz Araç Tipi"):
        dogrula_plan_formati(df)


# --- Muhasebe kontrolleri ---

def test_muhasebe_dogru():
    df = sahte_plan()
    dogrula_muhasebe(df)  # ilk satırda maliyet, ikincide 0 — doğru


def test_muhasebe_cift_maliyet():
    df = sahte_plan()
    df.loc[1, "Toplam maliyet"] = 3000.0  # iki satırda da maliyet var
    with pytest.raises(SimulasyonHatasi, match="birden fazla satırda"):
        dogrula_muhasebe(df)


# --- Talep bütünlüğü ---

def test_talep_butunlugu_dogru():
    plan = sahte_plan()
    tahmin = pd.DataFrame({"Talep ID": ["D00001", "D00002"]})
    dogrula_talep_butunlugu(plan, tahmin)  # hata yok


def test_talep_butunlugu_eksik():
    plan = sahte_plan()
    tahmin = pd.DataFrame({"Talep ID": ["D00001", "D00002", "D00003"]})
    with pytest.raises(SimulasyonHatasi, match="planda eksik"):
        dogrula_talep_butunlugu(plan, tahmin)