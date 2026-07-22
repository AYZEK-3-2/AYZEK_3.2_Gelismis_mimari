# -*- coding: utf-8 -*-
"""Katman 3: bağımsız simülatör ve kalite kapısı.

Yalnız çıktı dosyalarını okur; katman2'den import yapmak YASAK
(maliyet formülü dahil her şey burada ikinci kez yazılır).
Kapılar geçmeden teslim dosyası yazılmaz. Detay: issue #4-#7.
"""

from .simulator import simulasyonu_calistir, plan_oku
from .format_kapisi import dogrula_plan_formati, dogrula_muhasebe, dogrula_talep_butunlugu


def dogrula_ve_yaz(veri, tahmin, plan):
    """Simülasyonu çalıştır, format kapısını geç, sonucu döndür."""

    if plan is None:
        print("katman3: plan henüz üretilmedi, simülatör atlanıyor")
        return None

    # 1) Planı bir kez oku
    plan_df = plan_oku(plan)

    # 2) Simülasyonu çalıştır (df ile)
    sonuc = simulasyonu_calistir(plan_df, veri)

    # 3) Format kapısı kontrolleri
    dogrula_plan_formati(plan_df)
    dogrula_muhasebe(plan_df)
    dogrula_talep_butunlugu(plan_df, tahmin)

    print("katman3: tüm kapılar geçti ✓")
    return sonuc