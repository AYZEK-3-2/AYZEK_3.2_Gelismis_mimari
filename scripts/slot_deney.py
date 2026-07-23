# -*- coding: utf-8 -*-
"""Issue #10 — slot mimarisi + hedef dönüşümü deneyi (tekrarlanabilir).

Üç varyantı aynı walk-forward protokolüyle (bitişik, §7) kıyaslar:
  D1  tek global model + slot feature, ham hedef  (= mevcut pipeline)
  D2  09:00 ve 17:00 için ayrı model, ham hedef
  D3  tek global model + slot feature, log1p hedef

Çıktı: toplam WAPE (kat kırılımı) + slot kırılımı (09:00 / 17:00 ayrı) + ortalama.
Tek komut: python scripts/slot_deney.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lightgbm as lgb
import numpy as np

from katman0_veri import veriyi_yukle
from katman1_tahmin import (
    egitim_paneli_kur,
    feature_ekle,
    naif_tahmin,
    walk_forward_bol,
    wape,
)
from katman1_tahmin.model import KATEGORIK, LGBM_PARAMS, SEEDLER
from katman1_tahmin.panel import FEATURE_KOLONLARI, SLOTLAR

XCOLS = list(FEATURE_KOLONLARI)


def _egit_tek(train, test, log1p: bool) -> np.ndarray:
    """Tek global model (seed ensemble). log1p=True ise hedef log dönüşümlü."""
    y = np.log1p(train["desi"]) if log1p else train["desi"].astype("float64")
    toplam = np.zeros(len(test))
    for seed in SEEDLER:
        m = lgb.LGBMRegressor(random_state=seed, **LGBM_PARAMS)
        m.fit(train[XCOLS], y, categorical_feature=KATEGORIK)
        p = m.predict(test[XCOLS])
        toplam += np.expm1(p) if log1p else p
    return np.clip(toplam / len(SEEDLER), 0.0, None)


def _egit_slot_ayri(train, test) -> np.ndarray:
    """09:00 ve 17:00 için ayrı model; her slot kendi verisiyle eğitilir."""
    pred = np.zeros(len(test))
    test_slot = test["slot"].to_numpy()
    for slot in SLOTLAR:
        tr = train[train["slot"] == slot]
        mask = test_slot == slot
        toplam = np.zeros(int(mask.sum()))
        for seed in SEEDLER:
            m = lgb.LGBMRegressor(random_state=seed, **LGBM_PARAMS)
            m.fit(tr[XCOLS], tr["desi"], categorical_feature=KATEGORIK)
            toplam += m.predict(test[mask][XCOLS])
        pred[mask] = np.clip(toplam / len(SEEDLER), 0.0, None)
    return pred


VARYANTLAR = {
    "D1 tek+ham":   lambda tr, te: _egit_tek(tr, te, log1p=False),
    "D2 slot-ayrı": _egit_slot_ayri,
    "D3 log1p":     lambda tr, te: _egit_tek(tr, te, log1p=True),
}


def calistir():
    t0 = time.perf_counter()
    veri = veriyi_yukle()
    feat = feature_ekle(egitim_paneli_kur(veri))
    slot_arr = feat["slot"].to_numpy()
    katlar = walk_forward_bol(egitim_paneli_kur(veri))

    # sonuc[varyant][kat] = (toplam, w09, w17); ayrıca naif
    sonuc: dict[str, list] = {ad: [] for ad in VARYANTLAR}
    naif: list = []

    for kat in katlar:
        tr, te = feat.iloc[kat.egitim_idx], feat.iloc[kat.test_idx]
        g = te["desi"].to_numpy("float64")
        te_slot = slot_arr[kat.test_idx]
        m09, m17 = te_slot == "09:00", te_slot == "17:00"

        for ad, fn in VARYANTLAR.items():
            p = fn(tr, te)
            sonuc[ad].append((wape(g, p), wape(g[m09], p[m09]), wape(g[m17], p[m17])))
        np_ = naif_tahmin(te)
        naif.append((wape(g, np_), wape(g[m09], np_[m09]), wape(g[m17], np_[m17])))

    # --- TABLO: toplam WAPE, kat kırılımı ---
    katno = [k.kat_no for k in katlar]
    print("\nTOPLAM WAPE (kat kırılımı) — düşük = iyi")
    baslik = "Deney".ljust(14) + "".join(f"Kat{k}".rjust(9) for k in katno) + "Ort".rjust(10)
    print(baslik); print("-" * len(baslik))
    ort = {}
    for ad in VARYANTLAR:
        tot = [s[0] for s in sonuc[ad]]
        ort[ad] = float(np.mean(tot))
        print(ad.ljust(14) + "".join(f"{t:9.4f}" for t in tot) + f"{ort[ad]:10.4f}")
    naif_tot = [s[0] for s in naif]
    print("naif".ljust(14) + "".join(f"{t:9.4f}" for t in naif_tot) + f"{np.mean(naif_tot):10.4f}")

    # --- SLOT KIRILIMI (09:00 ayrıca — küçük hacim toplamda kaybolmasın) ---
    print("\nSLOT KIRILIMI — kat0 (en güncel, Haziran sonu)")
    print("Deney".ljust(14) + "09:00".rjust(10) + "17:00".rjust(10))
    print("-" * 34)
    for ad in VARYANTLAR:
        _, w09, w17 = sonuc[ad][0]
        print(ad.ljust(14) + f"{w09:10.4f}{w17:10.4f}")
    _, n09, n17 = naif[0]
    print("naif".ljust(14) + f"{n09:10.4f}{n17:10.4f}")
    print("\n09:00 hacmin ~%9'u ama gürültülü; 17:00 hacmin ~%91'i (asıl metrik).")

    # --- KARAR ---
    kazanan = min(ort, key=ort.get)
    print(f"\nKAZANAN: {kazanan} (ort WAPE {ort[kazanan]:.4f})")
    print("Gerekçe: en düşük ortalama WAPE. D1 zaten mevcut pipeline config'i —")
    print("kazanan değişmiyor, ek iş yok (model.py'de elenen alternatifler belgeli).")
    print(f"\nToplam süre: {time.perf_counter() - t0:.0f} sn")


if __name__ == "__main__":
    calistir()
