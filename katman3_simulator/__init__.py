# -*- coding: utf-8 -*-
"""Katman 3: bağımsız simülatör ve kalite kapısı.

Yalnız çıktı dosyalarını okur; katman2'den import yapmak YASAK
(maliyet formülü dahil her şey burada ikinci kez yazılır).
Kapılar geçmeden teslim dosyası yazılmaz. Detay: issue #4-#7.
"""
import dataclasses

import pandas as pd

from .simulator import simulasyonu_calistir, plan_oku
from .format_kapisi import dogrula_plan_formati, dogrula_muhasebe, dogrula_talep_butunlugu


def _sla_dogrulamasi_icin_talep(tahmin: pd.DataFrame) -> pd.DataFrame:
    """`tahmin` (Talep-tahmini.xlsx şeması) → `Kisitlar.talep`in beklediği
    şema (`talep_id, cikis, varis, tarih, slot`).

    `simulasyonu_calistir`in SLA kontrolü (`_hesapla_sla`) planın dayandığı
    GERÇEK talebe karşı doğrulama yapmalı — `Kisitlar.talep` (katman0'ın
    yüklediği tarihsel 66k satırlık tablo) DEĞİL. `talep_id_ata`'nın ürettiği
    ID'ler kasıtlı olarak tarihsel aralığın dışında (D70001+, "güvenli boşluk")
    başladığı için, doğrudan `veri.talep` kullanılırsa `_hesapla_sla` bu
    ID'leri hiç bulamaz ve kontrolü SESSİZCE atlar — greedy'nin ürettiği
    `SLA cezası` sütunu (yanlışsa bile) hiçbir zaman doğrulanmamış olurdu.
    """
    return pd.DataFrame({
        "talep_id": tahmin["Talep ID"],
        "cikis": tahmin["Çıkış Transfer Merkezi"],
        "varis": tahmin["Varış Transfer Merkezi"],
        "tarih": pd.to_datetime(tahmin["Tarih"], format="%d.%m.%Y"),
        "slot": tahmin["Talep Tamamlama Saati"].astype(str).str[:5],
        "toplam_desi": tahmin["Tahmin Edilen Desi"],
    })


def dogrula_ve_yaz(veri, tahmin, plan):
    """Simülasyonu çalıştır, format kapısını geç, sonucu döndür."""

    if plan is None:
        print("katman3: plan henüz üretilmedi, simülatör atlanıyor")
        return None

    # 1) Planı bir kez oku
    plan_df = plan_oku(plan)

    # 2) Simülasyonu çalıştır (df ile) — SLA kontrolü GERÇEK tahmine karşı
    veri_sim = dataclasses.replace(veri, talep=_sla_dogrulamasi_icin_talep(tahmin))
    sonuc = simulasyonu_calistir(plan_df, veri_sim)

    # 3) Format kapısı kontrolleri
    dogrula_plan_formati(plan_df)
    dogrula_muhasebe(plan_df)
    dogrula_talep_butunlugu(plan_df, tahmin)

    print("katman3: tum kapilar gecti [OK]")
    return sonuc