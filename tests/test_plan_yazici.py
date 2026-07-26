# -*- coding: utf-8 -*-
""" plan_yazici testleri."""
import os
import tempfile
from datetime import datetime

import pandas as pd
import pytest

from katman2_planlama.plan_yazici import (
    AracPlan, BacakAtama, TalepAtama,
    plan_yaz, SABLON_SUTUNLARI,
)
from katman3_simulator.simulator import plan_oku


def _dt(saat: str) -> datetime:
    return datetime(2026, 6, 29, int(saat[:2]), int(saat[3:]))


def _talep(tid, desi, son_bacak=True, sla_ceza=0.0):
    return TalepAtama(talep_id=tid, desi=desi, son_bacak=son_bacak, sla_ceza=sla_ceza)


def _bacak(cikis, varis, cs, vs, talepler, seyir_dk=60):
    return BacakAtama(
        cikis=cikis, varis=varis,
        cikis_ani=_dt(cs), varis_ani=_dt(vs),
        seyir_dk=seyir_dk, talepler=talepler,
    )


def _tek_arac(**kwargs):
    defaults = dict(arac_tipi="Tır", kiralik=False, toplam_maliyet=1000.0,
                    bacaklar=[_bacak("A", "B", "09:00", "11:00",
                                     [_talep("D00001", 5000)])])
    defaults.update(kwargs)
    return AracPlan(**defaults)


# --- sütunlar ---

def test_sutunlar_sablon_ile_ayni():
    df = plan_yaz([_tek_arac()])
    assert list(df.columns) == SABLON_SUTUNLARI


# --- araç ID ---

def test_arac_id_formati():
    araclar = [_tek_arac(toplam_maliyet=500.0), _tek_arac(toplam_maliyet=300.0)]
    df = plan_yaz(araclar)
    assert list(df["Araç ID"].unique()) == ["V0001", "V0002"]


# --- muhasebe: toplam maliyet ---

def test_toplam_maliyet_ilk_satirda():
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=5000.0,
        bacaklar=[_bacak("A", "B", "09:00", "11:00",
                         [_talep("D00001", 3000), _talep("D00002", 2000)])],
    )
    df = plan_yaz([arac])
    assert df.loc[0, "Toplam maliyet"] == 5000.0
    assert df.loc[1, "Toplam maliyet"] == 0.0


def test_iki_arac_maliyet_toplami():
    araclar = [_tek_arac(toplam_maliyet=1000.0), _tek_arac(toplam_maliyet=2000.0)]
    df = plan_yaz(araclar)
    assert df[df["Araç ID"] == "V0001"]["Toplam maliyet"].sum() == 1000.0
    assert df[df["Araç ID"] == "V0002"]["Toplam maliyet"].sum() == 2000.0


# --- muhasebe: SLA cezası ---

def test_sla_ceza_son_bacakta():
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=0.0,
        bacaklar=[
            _bacak("A", "B", "09:00", "11:00",
                   [_talep("D00001", 1000, son_bacak=False, sla_ceza=0.0)]),
            _bacak("B", "C", "12:00", "14:00",
                   [_talep("D00001", 1000, son_bacak=True, sla_ceza=400.0)]),
        ],
    )
    df = plan_yaz([arac])
    assert df.loc[0, "SLA cezası"] == 0.0
    assert df.loc[1, "SLA cezası"] == 400.0


# --- muhasebe: süreler ---

def test_sureler_bacak_ilk_satirinda():
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=0.0,
        bacaklar=[_bacak("A", "B", "09:00", "11:00",
                         [_talep("D00001", 5000), _talep("D00002", 3000)],
                         seyir_dk=90)],
    )
    df = plan_yaz([arac])
    assert df.loc[0, "Yolculuk süresi"] == 90
    assert df.loc[1, "Yolculuk süresi"] == 0
    assert df.loc[0, "Varış elleçleme süresi"] > 0
    assert df.loc[1, "Varış elleçleme süresi"] == 0


def test_ellecleme_suresi_hesabi():
    # 8000 desi → ceil(8000 * 0.01) = 80 dk
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=0.0,
        bacaklar=[_bacak("A", "B", "09:00", "11:00",
                         [_talep("D00001", 5000), _talep("D00002", 3000)])],
    )
    df = plan_yaz([arac])
    assert df.loc[0, "Çıkış Elleçleme süresi"] == 80
    assert df.loc[0, "Varış elleçleme süresi"] == 80


# --- araç tipi ---

def test_kiralik_tipi():
    df = plan_yaz([_tek_arac(kiralik=True)])
    assert df.loc[0, "Araç Tipi"] == "Kiralık"


def test_spot_tipi():
    df = plan_yaz([_tek_arac(kiralik=False)])
    assert df.loc[0, "Araç Tipi"] == "Spot"


# --- tarih/saat formatı ---

def test_tarih_saat_formati():
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=0.0,
        bacaklar=[_bacak("A", "B", "09:05", "14:30", [_talep("D00001", 100)])],
    )
    df = plan_yaz([arac])
    assert df.loc[0, "Çıkış Tarihi"] == "29.06.2026"
    assert df.loc[0, "Çıkış Saati"] == "09:05"
    assert df.loc[0, "Varış Saati"] == "14:30"


# --- talep bölme ID'leri ---

def test_bolme_id_yazilir():
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=0.0,
        bacaklar=[_bacak("A", "B", "09:00", "11:00",
                         [_talep("D00001-1", 5000), _talep("D00001-2", 3000)])],
    )
    df = plan_yaz([arac])
    assert list(df["Talep ID"]) == ["D00001-1", "D00001-2"]


# --- aktarmalı: şablondaki D00002 deseni ---

def test_aktarmali_talep_iki_bacak():
    """Aynı talep iki bacakta → iki satır, bacak bilgileri tekrar eder."""
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=1500.0,
        bacaklar=[
            _bacak("İstanbul", "Yalova", "09:00", "11:00",
                   [_talep("D00002", 5000, son_bacak=False)]),
            _bacak("Yalova", "Eskişehir", "12:00", "14:00",
                   [_talep("D00002", 5000, son_bacak=True)]),
        ],
    )
    df = plan_yaz([arac])
    assert len(df) == 2
    assert list(df["Talep ID"]) == ["D00002", "D00002"]
    assert list(df["Çıkış Transfer Merkezi"]) == ["İstanbul", "Yalova"]
    assert list(df["Varış Transfer Merkezi"]) == ["Yalova", "Eskişehir"]
    assert df["Toplam maliyet"].sum() == 1500.0


# --- sütun toplamları invariantı ---

def test_sutun_toplamlari_gercek_toplama_esit():
    """Her sütunun toplamı gerçek değere eşit (muhasebe invariantı)."""
    araclar = [
        AracPlan("Tır", False, [
            _bacak("A", "B", "09:00", "11:00",
                   [_talep("D00001", 3000), _talep("D00002", 2000)])
        ], toplam_maliyet=4000.0),
        AracPlan("Kamyon", True, [
            _bacak("A", "C", "10:00", "13:00",
                   [_talep("D00003", 1500, sla_ceza=200.0)])
        ], toplam_maliyet=2500.0),
    ]
    df = plan_yaz(araclar)
    assert df["Toplam maliyet"].sum() == 6500.0
    assert df["SLA cezası"].sum() == 200.0
    assert df["Taşınan Desi"].sum() == 6500.0


# --- gidiş-dönüş testi ---

def test_gidis_donus():
    """plan_yaz → xlsx → plan_oku aynı veriyi döndürmeli."""
    arac = AracPlan(
        arac_tipi="Tır", kiralik=False, toplam_maliyet=3000.0,
        bacaklar=[_bacak("A", "B", "09:00", "11:00",
                         [_talep("D00001", 5000), _talep("D00002", 3000)])],
    )
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        dosya = f.name
    try:
        df_yazilan = plan_yaz([arac], dosya_yolu=dosya)
        df_okunan = plan_oku(dosya)
        assert list(df_okunan.columns) == list(df_yazilan.columns)
        assert len(df_okunan) == len(df_yazilan)
        assert df_okunan["Toplam maliyet"].sum() == df_yazilan["Toplam maliyet"].sum()
        assert df_okunan["Taşınan Desi"].sum() == df_yazilan["Taşınan Desi"].sum()
    finally:
        os.unlink(dosya)

# --- format kapısı entegrasyon testi ---

def test_format_kapisi_geciliyor():
    """plan_yaz çıktısı format kapısından hatasız geçmeli."""
    from katman3_simulator.format_kapisi import dogrula_plan_formati, dogrula_muhasebe
    araclar = [
        AracPlan("Tır", False, [
            _bacak("A", "B", "09:00", "11:00",
                   [_talep("D00001", 5000), _talep("D00002", 3000)])
        ], toplam_maliyet=4000.0),
        AracPlan("Kamyon", True, [
            _bacak("A", "C", "10:00", "13:00",
                   [_talep("D00003", 1500, sla_ceza=200.0)])
        ], toplam_maliyet=2500.0),
    ]
    df = plan_yaz(araclar)
    dogrula_plan_formati(df)  # hata fırlatmamalı
    dogrula_muhasebe(df)      # hata fırlatmamalı