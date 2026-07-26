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
        "Çıkış Transfer Merkezi": ["İstanbul", "İstanbul"],
        "Varış Transfer Merkezi": ["Yalova", "Yalova"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "09:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:30", "10:30"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        # SIRA şablonla birebir: önce Varış, sonra Çıkış; sonra SLA, sonra maliyet
        "Varış elleçleme süresi": [80, 80],
        "Çıkış Elleçleme süresi": [80, 80],
        "SLA cezası": [0.0, 0.0],
        "Toplam maliyet": [5000.0, 0.0],
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


def test_muhasebe_sifir_sla_cezasi_sorun_degil():
    """Zamanında teslimde SLA cezası her satırda 0 olabilir — bu normaldir,
    hata değildir (docstring'te vaat edilen ama koda hiç yazılmamış SLA
    cezası kontrolü issue #22 canlı testinde eklendi)."""
    df = sahte_plan()
    dogrula_muhasebe(df)  # her iki satırda da SLA cezası 0.0 — hata yok


def test_muhasebe_cift_sla_cezasi():
    df = sahte_plan()
    df.loc[0, "Talep ID"] = "D00003"
    df2 = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # aynı Talep ID iki satırda
    df2.loc[0, "SLA cezası"] = 100.0
    df2.loc[2, "Toplam maliyet"] = 0.0  # tekrarlanan satır maliyet invariantını bozmasın
    df2.loc[2, "SLA cezası"] = 50.0
    with pytest.raises(SimulasyonHatasi, match="SLA cezası birden fazla satırda"):
        dogrula_muhasebe(df2)


# --- Talep bütünlüğü ---

def test_talep_butunlugu_dogru():
    plan = sahte_plan()
    tahmin = pd.DataFrame({
        "Talep ID": ["D00001", "D00002"],
        "Tahmin Edilen Desi": [5000.0, 3000.0],
    })
    dogrula_talep_butunlugu(plan, tahmin)  # hata yok


def test_talep_butunlugu_eksik():
    plan = sahte_plan()
    tahmin = pd.DataFrame({
        "Talep ID": ["D00001", "D00002", "D00003"],
        "Tahmin Edilen Desi": [5000.0, 3000.0, 100.0],
    })
    with pytest.raises(SimulasyonHatasi, match="planda eksik"):
        dogrula_talep_butunlugu(plan, tahmin)


def test_talep_butunlugu_sifir_desi_planda_olmasa_da_gecer():
    """0 desi öngörülen bir talep — taşınacak fiziksel bir şey yok, planda
    hiç yer almaması DOĞRU (issue #22 canlı testinde bulunan gerçek veri
    senaryosu: 632 talep tam olarak 0 tahminliydi)."""
    plan = sahte_plan()
    tahmin = pd.DataFrame({
        "Talep ID": ["D00001", "D00002", "D00003"],
        "Tahmin Edilen Desi": [5000.0, 3000.0, 0.0],
    })
    dogrula_talep_butunlugu(plan, tahmin)  # hata yok