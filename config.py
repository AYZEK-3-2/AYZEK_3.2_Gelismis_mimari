# -*- coding: utf-8 -*-
"""Şartname sabitleri.

Buraya yalnız şartnamede yazan, veriden okunamayan değerler girer.
Araç kapasitesi, kira, mesafe gibi her şey excel'den okunur (katman0_veri işi);
MVP'de config'e elle kopyalanan değerler kaynakla sessizce ayrışmıştı,
o hatayı tekrarlamıyoruz.
"""
from datetime import datetime
from pathlib import Path

PROJE_KOKU = Path(__file__).resolve().parent
VERI_KLASORU = PROJE_KOKU / "veri"
SABLON_KLASORU = VERI_KLASORU / "sablon"
CIKTI_KLASORU = PROJE_KOKU / "cikti"

# Elleçleme süresi: desi başına 0.01 dakika (şartname Ek Kısıt 1)
ELLECLEME_DK_PER_DESI = 0.01

# Tavan (⌈⌉) alırken yok sayılacak float gürültüsü, DAKİKA cinsinden.
# Bir aracın yükü artık birden fazla talep diliminin toplamıdır; ardışık
# toplama/çıkarma float64'te son bit'te sapma bırakır (12000.0 yerine
# 12000.000000000002 gibi). Ham `ceil` bunu gerçek bir kesir sanıp süreyi
# 1 dakika şişirir ve — katman2 ile katman3 toplamı FARKLI sırada yaptığı
# için — kuruş kapısını araç başına ±6,60 / ±10,61 TL (tam bir dakikalık
# kira) sapmayla kırar; gerçek veride canlı olarak ölçüldü.
# 1e-9 dakika = 1e-7 desi: şartnamenin hassasiyetinin çok altında, yani
# gerçek bir kesri asla yutmaz, yalnız gürültüyü siler.
TAVAN_TOLERANSI_DK = 1e-9

# SLA cezası: geciken desi x gecikme saati (üst tam saate yuvarlanır) x 0.4 TL
SLA_CEZA_TL_PER_DESI_SAAT = 0.4

# Talep tamamlanma saatleri; aynı zamanda SLA başlangıç anları
TALEP_SAATLERI = ("09:00", "17:00")

# ID formatları
TALEP_ID_SABLON = "D{:05d}"   # D00001
ARAC_ID_SABLON = "V{:04d}"    # V0001

# Tahmin ufku (jüri cevabı: 29 Haziran 09:00 - 5 Temmuz 17:00)
TAHMIN_BASLANGIC = datetime(2026, 6, 29, 9, 0)
TAHMIN_BITIS = datetime(2026, 7, 5, 17, 0)

# Beklenen tahmin çıktısı: 289 hat x 7 gün x 2 slot
TAHMIN_SATIR_SAYISI = 4046

# Determinizm: teslim edilen dosyalar her koşuda bit düzeyinde aynı olmalı
SEED = 42

# Katman 2 · Set-partitioning MILP (mimari §5.4)
MILP_ZAMAN_LIMIT_SN = 60.0     # kabul kriteri: 1 günlük dilim bu sürede fizibil çözüm
MILP_DESI_OLCEK = 100          # CP-SAT tam sayı gerektirir; 0.01 desi hassasiyeti
MILP_MAX_GECIKME_GUN = 3       # f[emtia,kenar] zaman penceresi filtresi (SLA <= 2 gün + tolerans)
MILP_GORECELI_GAP = 0.01       # %1 içinde kanıtlanmış-yeterli kabul et — sıfır gap'i ıspatlamak
                                # için harcanan (genelde en pahalı) son kısmı hızlandırır

# Kayan pencere (mimari §5.4 "en büyük risk" azaltımı — issue #21)
KAYAN_PENCERE_GUN = 3          # pencere genişliği (SLA <= 2 gün + 1 gün tolerans)
KAYAN_PENCERE_ADIM_GUN = 1     # her adımda yalnız ilk gün commit edilir, pencere 1 gün ilerler
# MILP_ZAMAN_LIMIT_SN (#20) TEK bir 1-günlük çözüm için kalibre edildi; kayan pencere
# MILP'i pencere başına (5-7 kez) çağırdığı için aynı süreyi kullanmak toplam süreyi
# kat kat şişirir. CP-SAT bu ölçekte küçük bir gap'e asla hızlı yakınsamıyor (gap
# genelde %75+ kalıyor, süre sınırına her koşulda çarpıyor) — ama kısa bütçede bile
# bulduğu çözüm greedy'den kat kat ucuz kalıyor (kıyas+fallback zaten garantisi).
KAYAN_PENCERE_ZAMAN_LIMIT_SN = 3.0

# Katman 2 · LNS iyileştirme turu (mimari §5.5, issue #22 — "zaman kalırsa")
LNS_SURE_BUTCE_SN = 60.0          # tüm yık-onar turunun toplam süre bütçesi
LNS_KOMSULUK_ZAMAN_LIMIT_SN = 3.0  # tek bir TM-gün komşuluğu onarımı için MILP süresi
# emtia × aday üst sınırı — milp_cozucu.py'nin kendi ölçek notu (§5.4) "1 günlük
# dilim ve mini örnekler" icin tasarlandığını, geniş ölçeğin AYRI bir performans
# issue'su olduğunu söylüyor; gerçek veride yoğun bir TM'nin çok günlük komşuluğu
# bu sınırı büyük farkla aşabiliyor ve model KURULUMU (solver süre sınırının
# GÖREMEDİĞİ Python aşaması) dakikalar sürebiliyor (issue #22 canlı testinde
# bulundu). Aşılırsa o komşuluk denemesi hiç yapılmadan "aday üretilemedi" sayılır.
LNS_MAX_MODEL_OLCEK = 5_000
