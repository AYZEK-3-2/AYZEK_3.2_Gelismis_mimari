# -*- coding: utf-8 -*-
"""LightGBM tahmin modeli, naif taban çizgisi ve walk-forward backtest.

Mimari §7: tek global model (hat başına ayrı model YOK), direct multi-step,
seed ensemble. Metrik saf WAPE. Puanlama tahmini gerçekle kıyaslıyor ama
optimizasyon kendi tahminimiz üzerinden değerlendiriliyor; o yüzden tahmini
bilerek kaydırmıyoruz, saf doğruluk kovalıyoruz.

Backtest split BİTİŞİK (mimari §7, #8'de düzeltildi): test penceresi eğitimin
hemen ardından gelir, gerçek görevle (origin'den 1..7 gün) aynı horizon.
Sızıntıyı boşluk değil, feature'ların >=7 gün geriden başlaması önler.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

import config
from katman0_veri import Kisitlar

from .bolme import walk_forward_bol
from .metrik import wape
from .panel import (
    FEATURE_KOLONLARI,
    SLOTLAR,
    egitim_paneli_kur,
    feature_ekle,
    tahmin_paneli_kur,
)

# Backtest ile ELENEN alternatifler (tekrar denemeyin, veri karar verdi):
#   - log1p hedef dönüşümü: Haziran katlarında belirgin kötü (WAPE weighted,
#     log büyük değerleri sıkıştırıp modeli önemli günlerden uzaklaştırıyor)
#   - slot başına ayrı model: başa baş ama daha kırılgan (tek model daha iyi)
#   - yakınlık ağırlığı (recency sample weight): Haziran'ı kötüleştirdi
#     (eski veri mevsimsel/hat yapısı için gerekli örnek, kısınca sinyal gidiyor)
#
# L1 (MAE) hedefi WAPE ile hizalı — ikisi de mutlak hata. deterministic +
# force_row_wise ile çok çekirdekte bile tekrarlanabilir.
LGBM_PARAMS = dict(
    objective="regression_l1",
    n_estimators=400,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=50,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    deterministic=True,
    force_row_wise=True,
    verbose=-1,
    n_jobs=-1,
)
KATEGORIK = ["hat"]
SEEDLER = (1, 2, 3)


def naif_tahmin(test_df: pd.DataFrame) -> np.ndarray:
    """Naif taban çizgisi: geçen haftanın aynı günü + aynı slotu (= lag_7).

    Haftanın günü etkisi ~20x olduğu için bu şaşırtıcı derecede güçlü bir
    kıyas; model bunu yenemezse karmaşıklığın anlamı yok (mimari §7).
    """
    return test_df["lag_7"].fillna(0.0).clip(lower=0).to_numpy()


def egit_ve_tahmin(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    seedler: tuple[int, ...] = SEEDLER,
    n_estimators: int | None = None,
) -> np.ndarray:
    """Seed ensemble LightGBM: her seed için bir model, tahminlerin ortalaması.

    Negatif tahminler 0'a çekilir (zero-floor); talep negatif olamaz.
    """
    X_tr = train_df[list(FEATURE_KOLONLARI)]
    y_tr = train_df["desi"]
    X_te = test_df[list(FEATURE_KOLONLARI)]

    params = dict(LGBM_PARAMS)
    if n_estimators is not None:
        params["n_estimators"] = n_estimators

    toplam = np.zeros(len(test_df), dtype="float64")
    for seed in seedler:
        model = lgb.LGBMRegressor(random_state=seed, **params)
        model.fit(X_tr, y_tr, categorical_feature=KATEGORIK)
        toplam += model.predict(X_te)
    return np.clip(toplam / len(seedler), 0.0, None)


@dataclass
class KatSonuc:
    kat_no: int
    test_araligi: str
    model_wape: float
    naif_wape: float
    model_wape_slot: dict[str, float]
    naif_wape_slot: dict[str, float]


def backtest(
    veri: Kisitlar,
    seedler: tuple[int, ...] = SEEDLER,
    n_estimators: int | None = None,
) -> list[KatSonuc]:
    """Walk-forward backtest: her kat için model ve naif WAPE (toplam + slot)."""
    panel = egitim_paneli_kur(veri)
    feat = feature_ekle(panel)
    slot_arr = feat["slot"].to_numpy()

    sonuclar: list[KatSonuc] = []
    for kat in walk_forward_bol(panel):
        train_df = feat.iloc[kat.egitim_idx]
        test_df = feat.iloc[kat.test_idx]

        gercek = test_df["desi"].to_numpy(dtype="float64")
        model_pred = egit_ve_tahmin(train_df, test_df, seedler, n_estimators)
        naif_pred = naif_tahmin(test_df)

        test_slot = slot_arr[kat.test_idx]
        m_slot, n_slot = {}, {}
        for slot in SLOTLAR:
            mask = test_slot == slot
            m_slot[slot] = wape(gercek[mask], model_pred[mask])
            n_slot[slot] = wape(gercek[mask], naif_pred[mask])

        sonuclar.append(
            KatSonuc(
                kat_no=kat.kat_no,
                test_araligi=f"{kat.test_baslangic.date()}..{kat.test_bitis.date()}",
                model_wape=wape(gercek, model_pred),
                naif_wape=wape(gercek, naif_pred),
                model_wape_slot=m_slot,
                naif_wape_slot=n_slot,
            )
        )
    return sonuclar


def tahmin_uret(veri: Kisitlar, seedler: tuple[int, ...] = SEEDLER) -> pd.DataFrame:
    """Tahmin ufku (29 Haz–5 Tem) için desi tahmini üretir.

    Tüm geçmişle eğitilir, tahmin haftasını tahmin eder (direct multi-step;
    lag/rolling yalnız geçmişe bakar). Döner: 4.046 satır DataFrame —
    (tarih, cikis, varis, slot, tahmin_desi), negatifler 0'a çekilmiş.
    """
    import config

    feat = feature_ekle(tahmin_paneli_kur(veri))
    ufuk_bas = pd.Timestamp(config.TAHMIN_BASLANGIC.date())
    egitim = feat[feat["tarih"] < ufuk_bas]
    ufuk = feat[feat["tarih"] >= ufuk_bas]

    tahmin = egit_ve_tahmin(egitim, ufuk, seedler)  # zero-floor içeride

    out = ufuk[["tarih", "cikis", "varis", "slot"]].copy()
    out["tahmin_desi"] = tahmin
    return out.reset_index(drop=True)


def rapor_yazdir(sonuclar: list[KatSonuc]) -> bool:
    """Backtest sonuçlarını tablo olarak yazdırır, kabul kriterini döndürür.

    Kabul: model, en güncel katta (kat 0 = Haziran sonu) naifi yener.
    """
    print(f"{'Kat':<4}{'Test':<24}{'Model WAPE':>12}{'Naif WAPE':>12}{'Kazanan':>10}")
    print("-" * 62)
    for s in sonuclar:
        kazanan = "model" if s.model_wape < s.naif_wape else "NAİF"
        print(f"{s.kat_no:<4}{s.test_araligi:<24}{s.model_wape:>12.4f}{s.naif_wape:>12.4f}{kazanan:>10}")
    print("-" * 62)
    print("Slot bazında (kat 0):")
    k0 = sonuclar[0]
    for slot in SLOTLAR:
        print(f"  {slot}: model {k0.model_wape_slot[slot]:.4f} | naif {k0.naif_wape_slot[slot]:.4f}")

    kabul = sonuclar[0].model_wape < sonuclar[0].naif_wape
    print()
    print(f"KABUL (kat 0'da model naifi yeniyor): {'EVET' if kabul else 'HAYIR'}")
    return kabul


def main() -> None:
    """Tek komut: python -m katman1_tahmin.model"""
    from katman0_veri import veriyi_yukle

    t0 = time.perf_counter()
    veri = veriyi_yukle()
    sonuclar = backtest(veri)
    kabul = rapor_yazdir(sonuclar)
    print(f"Backtest süresi: {time.perf_counter() - t0:.1f} sn")
    if not kabul:
        raise SystemExit("Model naif taban çizgisini yenemedi — basitleştirme kararı gerekli (§7).")


if __name__ == "__main__":
    main()
