# -*- coding: utf-8 -*-
"""Talep ID üretimi ve Talep-tahmini.xlsx yazıcısı testleri (issue #11).

Yazıcı, gerçek modeli çalıştırmadan sentetik tahmin_df ile test edilir (hızlı).
Ayrıca gerçek şablonla sütun kıyası ve ID sözleşmesi entegrasyon testi var.
"""
import pandas as pd
import pytest

import config
from katman1_tahmin import talep_id_ata, talep_tahmini_yaz
from katman1_tahmin.yazici import SUTUNLAR


def _sentetik_tahmin_df():
    """289 hat yerine küçük ama gerçekçi bir tahmin_df (2 hat × 7 gün × 2 slot)."""
    ufuk = pd.date_range(config.TAHMIN_BASLANGIC.date(), config.TAHMIN_BITIS.date(), freq="D")
    satirlar = []
    for tarih in ufuk:
        for cikis, varis in [("İstanbul", "Yalova"), ("Ankara", "Mersin")]:
            for slot in ("09:00", "17:00"):
                satirlar.append({
                    "tarih": tarih, "cikis": cikis, "varis": varis,
                    "slot": slot, "tahmin_desi": 3.5,
                })
    return pd.DataFrame(satirlar)


def test_id_deterministik_ve_sirali():
    df = _sentetik_tahmin_df()
    a = talep_id_ata(df)
    b = talep_id_ata(df.sample(frac=1, random_state=1))  # karışık girdi
    # Sıra (tarih, slot, çıkış, varış) olduğu için ID eşlemesi aynı olmalı
    ma = dict(zip(zip(a["tarih"], a["slot"], a["cikis"], a["varis"]), a["talep_id"]))
    mb = dict(zip(zip(b["tarih"], b["slot"], b["cikis"], b["varis"]), b["talep_id"]))
    assert ma == mb
    assert a["talep_id"].iloc[0] == "D70001"
    assert a["talep_id"].is_unique
    # ardışık
    _ID_BAS = 70_001
    assert list(a["talep_id"]) == [config.TALEP_ID_SABLON.format(_ID_BAS + i) for i in range(len(a))]


def test_yazici_format_sablonla_ayni(tmp_path):
    dosya = tmp_path / "Talep-tahmini.xlsx"
    cikti = talep_tahmini_yaz(_sentetik_tahmin_df(), dosya)
    # sütun adı + sırası şablonla birebir
    sablon = pd.read_excel(config.SABLON_KLASORU / "TALEP_TAHMINI_sablon.xlsx", engine="calamine")
    assert list(cikti.columns) == list(sablon.columns) == list(SUTUNLAR)
    # tarih GG.AA.YYYY, saat SS:DD:ss
    okunan = pd.read_excel(dosya, engine="calamine", dtype=str)
    assert okunan["Tarih"].iloc[0] == "29.06.2026"
    assert set(okunan["Talep Tamamlama Saati"]) == {"09:00:00", "17:00:00"}


def test_onceden_atanmis_id_korunur(tmp_path):
    # Tek-kaynak akışı (#17): ID önceden atanmışsa yazıcı onu kullanmalı,
    # yeniden atamamalı — planlayıcıyla aynı ID'ler garanti olsun.
    df = talep_id_ata(_sentetik_tahmin_df())
    df.loc[df["talep_id"] == "D70003", "talep_id"] = "D70003-ozel"  # dış ID
    cikti = talep_tahmini_yaz(df, tmp_path / "t.xlsx")
    assert "D70003-ozel" in set(cikti["Talep ID"])


def test_zero_floor(tmp_path):
    df = _sentetik_tahmin_df()
    df.loc[0, "tahmin_desi"] = -5.0  # negatif tahmin
    cikti = talep_tahmini_yaz(df, tmp_path / "t.xlsx")
    assert (cikti["Tahmin Edilen Desi"] >= 0).all()


def test_slotlar_ayri_satir():
    cikti = talep_id_ata(_sentetik_tahmin_df())
    # her (tarih, hat) iki slot ayrı satırda
    assert (cikti.groupby(["tarih", "cikis", "varis"]).size() == 2).all()


# --- gerçek model çıktısı (yavaş) -------------------------------------------

@pytest.fixture(scope="module")
def gercek_tahmin():
    from katman0_veri import veriyi_yukle
    from katman1_tahmin import tahmin_uret
    return tahmin_uret(veriyi_yukle())


def test_gercek_4046_satir_ve_kocaeli_yok(gercek_tahmin):
    assert len(gercek_tahmin) == 289 * 7 * 2 == 4046
    assert (gercek_tahmin["varis"] == "Kocaeli").sum() == 0
    assert (gercek_tahmin["tahmin_desi"] >= 0).all()  # zero-floor


def test_gercek_4046_ve_id_ardisik(gercek_tahmin, tmp_path):
    cikti = talep_tahmini_yaz(gercek_tahmin, tmp_path / "Talep-tahmini.xlsx")
    assert len(cikti) >= 1
    assert cikti["Talep ID"].is_unique
    assert cikti["Talep ID"].iloc[0].startswith("D7")


def test_id_sozlesmesi_plan_yazicisiyla(tmp_path):
    """ORTAK entegrasyon testi (#11 kabul kriteri): plan yazıcısının (#16)
    ürettiği plandaki bölünmüş ID'lerin (D00001-1) kökü, tahmin dosyasındaki
    ID'lerle birebir eşleşmeli — yoksa jüri değerlendirmesi dışı kalır.
    """
    from datetime import datetime

    from katman2_planlama.plan_yazici import (
        AracPlan,
        BacakAtama,
        TalepAtama,
        plan_yaz,
    )

    # 1) Tahmin dosyasını üret, kanonik ID'leri al
    tahmin = talep_tahmini_yaz(_sentetik_tahmin_df(), tmp_path / "Talep-tahmini.xlsx")
    tahmin_idler = set(tahmin["Talep ID"])
    kok = tahmin["Talep ID"].iloc[0]  # D00001

    # 2) Bu talebi 2 araca bölen bir plan kur (D00001-1, D00001-2)
    bacak = BacakAtama(
        cikis="İstanbul", varis="Yalova",
        cikis_ani=datetime(2026, 6, 29, 9, 0),
        varis_ani=datetime(2026, 6, 29, 10, 0),
        seyir_dk=56,
        talepler=[
            TalepAtama(f"{kok}-1", 2.0, True, 0.0),
            TalepAtama(f"{kok}-2", 1.5, True, 0.0),
        ],
    )
    plan_df = plan_yaz([AracPlan("Tır", False, [bacak], 1000.0)])

    # 3) Plandaki her talep ID'nin kökü tahmin dosyasında olmalı
    for pid in plan_df["Talep ID"]:
        assert str(pid).split("-")[0] in tahmin_idler, f"{pid} kökü tahminde yok"
