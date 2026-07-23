# -*- coding: utf-8 -*-
"""Eğitim paneli ve feature üretimi.

Katman 0'ın ham (seyrek) talebini, tahmin için gereken **yoğun** panele
çevirir: 289 aktif hat × 179 gün × 2 slot = 103.462 satır. Talep görülmeyen
(gün, hat, slot) kombinasyonu **0 desi** ile doldurulur — bu şart, çünkü
ham veri yalnız %63,8 dolu ve sıfırlar atlanırsa model talebi sistematik
olarak yüksek tahmin eder.

Feature'lar sızıntısızdır: hedefe bağlı her feature (lag, rolling) yalnız
GEÇMİŞE bakar (`.shift`). Takvim feature'ları (haftanın günü, gün indeksi,
slot) gelecekte de bilindiği için sızıntı sayılmaz.

Sızıntı güvenliğinin ASIL kaynağı geriye bakış mesafesidir: hedefe bağlı her
feature en az UFUK_GUN (7) gün geriden başlar. 28 Haziran'dan 29 Haz–5 Tem
tahmin edilirken, bloğun son günü (5 Tem) için bile lag_7 = 28 Haziran = origin
(biliniyor). Yani hiçbir feature, 7 günlük tahmin penceresi içindeki bir güne
(henüz bilinmeyen) bakmaz. Bunun için lag'lar 7/14/28 ve rolling `shift(UFUK_GUN)`
ile başlar — `shift(1)` kullanılsaydı rolling, direct multi-step'te sonraki
tahmin günlerinin desisine bakıp sızdırırdı.

BİLİNEN SINIR (issue #9/#10 için) — `gun_index` ekstrapolasyonu: LightGBM ağaç
tabanlı olduğu için bir feature'ın eğitimde görülen aralığının ÖTESİNE
genelleyemez. Tahmin haftasında gun_index 179–185 olur (eğitim max'ı 178);
model bu satırları en sağdaki yaprağa atar ve trendi SÜRDÜRMEZ, son seviyeyi
tahmin eder. Trend'i asıl taşıyan lag/rolling'dir; gun_index yalnız yardımcı.
Sürekli büyümeyi yakalamak #9/#10'un işi (detrend / log1p hedef — §7).
"""
from __future__ import annotations

import pandas as pd

from katman0_veri import Kisitlar

SLOTLAR: tuple[str, ...] = ("09:00", "17:00")

# Tahmin ufku (gün). Hedefe bağlı feature'lar en az bu kadar geriden başlar ki
# 7 günlük tahmin bloğunu origin'den aynı anda tahmin ederken sızıntı olmasın.
UFUK_GUN: int = 7

# Modelin (issue #9) kullanacağı feature kolonları — tek kaynak.
FEATURE_KOLONLARI: tuple[str, ...] = (
    "hafta_gunu",       # 0=Pzt .. 6=Paz — en güçlü sinyal (~20x salınım)
    "gun_index",        # 01.01'den bu yana gün — trend (Ocak→Haziran %75 artış)
    "slot_kod",         # 09:00=0, 17:00=1
    "slot_dow",         # slot × haftanın günü etkileşimi (0..13)
    "hat",              # hat kimliği (kategori) — 289 hat
    "lag_7", "lag_14", "lag_28",         # aynı slot, geçmiş desi
    "rolling_ort_7", "rolling_ort_28",   # aynı slot, geçmiş ortalama
)


def egitim_paneli_kur(veri: Kisitlar) -> pd.DataFrame:
    """Yoğun eğitim paneli: her (aktif hat × gün × slot) için bir satır.

    Sütunlar: tarih, cikis, varis, slot, desi (talep yoksa 0).
    Deterministik sıralı; aynı girdi → bit düzeyinde aynı çıktı.
    """
    tarihler = pd.date_range(veri.talep["tarih"].min(), veri.talep["tarih"].max(), freq="D")
    hatlar = pd.DataFrame(veri.aktif_hatlar, columns=["cikis", "varis"])

    panel = (
        hatlar
        .merge(pd.DataFrame({"tarih": tarihler}), how="cross")
        .merge(pd.DataFrame({"slot": list(SLOTLAR)}), how="cross")
    )

    talep = veri.talep[["tarih", "cikis", "varis", "slot", "toplam_desi"]]
    panel = panel.merge(talep, on=["tarih", "cikis", "varis", "slot"], how="left")
    panel["desi"] = panel["toplam_desi"].fillna(0).astype("int64")
    panel = panel.drop(columns="toplam_desi")

    return panel.sort_values(["cikis", "varis", "slot", "tarih"]).reset_index(drop=True)


def tahmin_paneli_kur(veri: Kisitlar) -> pd.DataFrame:
    """Geçmiş + tahmin ufku (29 Haz–5 Tem) tek panelde.

    Gelecek satırları desi=0 yer tutucu; feature'lar >= UFUK_GUN geriden
    başladığı için tahmin haftasının lag/rolling'i yalnız GEÇMİŞE bakar
    (5 Tem için bile lag_7 = 28 Haz = veri sonu). Böylece tahmin haftası için
    feature'lar gerçek tahmin anında hesaplanabilir olur (yer tutucu 0'lar
    kendi satırlarının feature'ını etkilemez).
    """
    import config

    gecmis = egitim_paneli_kur(veri)
    ufuk = pd.date_range(config.TAHMIN_BASLANGIC.date(), config.TAHMIN_BITIS.date(), freq="D")
    hatlar = pd.DataFrame(veri.aktif_hatlar, columns=["cikis", "varis"])
    gelecek = (
        hatlar
        .merge(pd.DataFrame({"tarih": ufuk}), how="cross")
        .merge(pd.DataFrame({"slot": list(SLOTLAR)}), how="cross")
    )
    gelecek["desi"] = 0
    gelecek = gelecek[["cikis", "varis", "tarih", "slot", "desi"]]

    panel = pd.concat([gecmis, gelecek], ignore_index=True)
    return panel.sort_values(["cikis", "varis", "slot", "tarih"]).reset_index(drop=True)


def feature_ekle(panel: pd.DataFrame) -> pd.DataFrame:
    """Panele sızıntısız feature kolonları ekler.

    Lag/rolling yalnız geçmişe bakar (`shift`). Takvim feature'ları gelecekte
    de bilinir. Dönüş: yeni kolonlar eklenmiş kopya.
    """
    p = panel.sort_values(["cikis", "varis", "slot", "tarih"]).reset_index(drop=True)

    p["hafta_gunu"] = p["tarih"].dt.dayofweek.astype("int64")
    p["gun_index"] = (p["tarih"] - p["tarih"].min()).dt.days.astype("int64")
    p["slot_kod"] = (p["slot"] == "17:00").astype("int64")
    p["slot_dow"] = p["slot_kod"] * 7 + p["hafta_gunu"]
    p["hat"] = (p["cikis"] + "→" + p["varis"]).astype("category")

    grp = p.groupby(["cikis", "varis", "slot"], sort=False)["desi"]
    for lag in (7, 14, 28):
        p[f"lag_{lag}"] = grp.shift(lag)
    for w in (7, 28):
        # shift(UFUK): rolling penceresi hedeften >= 7 gün geride biter. 7 günlük
        # tahmin bloğunu ORIGIN'den aynı anda (direct multi-step) tahmin ederken,
        # sonraki tahmin günlerinin (henüz bilinmeyen) desisine bakmayı önler.
        # shift(1) kullanılsaydı origin+7 için pencere origin sonrasına taşardı.
        p[f"rolling_ort_{w}"] = grp.transform(
            lambda s, _w=w: s.shift(UFUK_GUN).rolling(_w, min_periods=1).mean()
        )

    return p


def hedef_donustur(panel: pd.DataFrame, yontem: str = "ham") -> pd.Series:
    """Hedef (desi) dönüşümü — issue #10 deneyinde kullanılacak.

    'ham' → desi olduğu gibi; 'log1p' → log(1+desi). Ters dönüşüm expm1.
    """
    import numpy as np

    if yontem == "ham":
        return panel["desi"].astype("float64")
    if yontem == "log1p":
        return np.log1p(panel["desi"].astype("float64"))
    raise ValueError(f"Bilinmeyen dönüşüm: {yontem!r} (ham|log1p)")
