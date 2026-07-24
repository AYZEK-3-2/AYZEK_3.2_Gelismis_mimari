# -*- coding: utf-8 -*-
"""Talep-tahmini.xlsx yazıcısı ve talep ID üretimi (issue #11).

Şablon (veri/sablon/TALEP_TAHMINI_sablon.xlsx) 6 sütun: Talep ID, Tarih,
Talep Tamamlama Saati, Çıkış Transfer Merkezi, Varış Transfer Merkezi,
Tahmin Edilen Desi. Format plan dosyasından bilerek farklı: Tarih GG.AA.YYYY
metin, Saat SS:DD:ss metin (09:00:00), 09:00 ve 17:00 ayrı satırlarda.

ID SÖZLEŞMESİ (plan yazıcısı #16 de aynısını kullanmalı): talep ID'leri
(tarih, slot, çıkış, varış) sırasına göre D00001'den deterministik üretilir.
Plan dosyasındaki bölünmüş parçaların (D00001-1) kökü bu dosyadaki ID'dir.
"""
from __future__ import annotations

import pandas as pd

import config

# Şablon sütunları — sıra ve ad birebir korunmalı.
SUTUNLAR: tuple[str, ...] = (
    "Talep ID", "Tarih", "Talep Tamamlama Saati",
    "Çıkış Transfer Merkezi", "Varış Transfer Merkezi", "Tahmin Edilen Desi",
)
_SAAT_METIN = {"09:00": "09:00:00", "17:00": "17:00:00"}
# ID sıralama anahtarı — plan yazıcısı (#16) bununla birebir eşleşmeli.
ID_SIRA = ["tarih", "slot", "cikis", "varis"]


def talep_id_ata(tahmin_df: pd.DataFrame) -> pd.DataFrame:
    """(tarih, slot, çıkış, varış) sırasına göre D00001'den ardışık ID atar.

    Deterministik; aynı girdi → aynı ID eşlemesi. Dönen kopya `talep_id`
    kolonu içerir ve ID sırasına göre sıralanmıştır.
    """
    df = tahmin_df.sort_values(ID_SIRA, kind="stable").reset_index(drop=True)
    df["talep_id"] = [config.TALEP_ID_SABLON.format(i + 1) for i in range(len(df))]
    return df


def talep_tahmini_yaz(tahmin_df: pd.DataFrame, dosya) -> pd.DataFrame:
    """`tahmin_df` (tarih, cikis, varis, slot, tahmin_desi) → Talep-tahmini.xlsx.

    Negatifler 0'a çekilir (zero-floor), şablon formatında yazılır. Yazılan
    DataFrame'i döner (test/doğrulama için).

    ID SÖZLEŞMESİ — önerilen akış (#17): ID'yi `talep_id_ata` ile bir kez ata,
    ID'li talebi hem buraya hem planlayıcıya ver (tek doğruluk kaynağı). Bu
    fonksiyon `talep_id` kolonu VARSA onu kullanır (yeniden atamaz), yoksa
    kendisi atar — böylece iki dosya arasında ID uyuşmazlığı imkânsız olur.
    """
    if "talep_id" in tahmin_df.columns:
        df = tahmin_df.sort_values("talep_id", kind="stable").reset_index(drop=True)
    else:
        df = talep_id_ata(tahmin_df)
    desi = df["tahmin_desi"].astype("float64").clip(lower=0.0)  # zero-floor

    cikti = pd.DataFrame({
        "Talep ID": df["talep_id"],
        "Tarih": pd.to_datetime(df["tarih"]).dt.strftime("%d.%m.%Y"),
        "Talep Tamamlama Saati": df["slot"].map(_SAAT_METIN),
        "Çıkış Transfer Merkezi": df["cikis"],
        "Varış Transfer Merkezi": df["varis"],
        "Tahmin Edilen Desi": desi,
    })

    if cikti["Talep Tamamlama Saati"].isna().any():
        gecersiz = set(df.loc[cikti["Talep Tamamlama Saati"].isna(), "slot"])
        raise ValueError(f"Beklenmeyen slot değeri: {gecersiz}")

    cikti = cikti[list(SUTUNLAR)]
    cikti.to_excel(dosya, index=False)
    return cikti
