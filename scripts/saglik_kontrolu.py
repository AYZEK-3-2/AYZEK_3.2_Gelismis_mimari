# -*- coding: utf-8 -*-
"""Mimari §10 saglik testleri — cikti plani uzerinde.

Kullanim:  python scripts/saglik_kontrolu.py cikti/

Bu testlerin basarisizligi HATA DEGIL, UYARIDIR — ama arastirilir. Mimari §10:
"bir saglik testinin yanlis olmasi, olmamasindan beterdir", o yuzden her uyarinin
yaninda hangi olcumden geldigi de yazilir.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from katman0_veri import veriyi_yukle

CIKIS = "Çıkış Transfer Merkezi"
VARIS = "Varış Transfer Merkezi"

cikti = Path(sys.argv[1])
plan = pd.read_excel(cikti / "Tasima-plani.xlsx")
veri = veriyi_yukle()

uyari = 0


def bak(ad, temiz, detay=""):
    global uyari
    if temiz:
        print(f"  [OK]    {ad}")
    else:
        uyari += 1
        print(f"  [SUPHE] {ad}\n          {detay}")


print("=== Mimari §10 saglik testleri ===\n")

# Bacak bazinda tekillestir (satir birimi (arac, bacak, talep))
bacak = plan.drop_duplicates(["Araç ID", CIKIS, VARIS, "Çıkış Tarihi", "Çıkış Saati"])
tir = bacak[bacak["Araç türü"] == "Tır"]

# 1) SPOT tir kisa hatta (<100 km) cikiyorsa suphe.
#    DIKKAT: yalnizca SPOT tirlar. Kiralik araclarin rotasi ve turu sozlesmeyle
#    sabittir (mimari §3: "rota sabit, donus yok, talep yetersiz olsa bile cikmak
#    zorunlu") — bizim SECIMIMIZ degil, VERI. Kiralik dahil edilirse test gercek
#    veride 14 yanlis alarm veriyor (Istanbul->Yalova 60 km, Kocaeli->Yalova 75 km
#    kiralik tirlari) ve dogru kodu "duzelttirmeye" calisir.
spot_tir = tir[tir["Araç Tipi"] == "Spot"]
tir_km = (spot_tir.apply(lambda r: veri.mesafe_km(r[CIKIS], r[VARIS]), axis=1)
          if len(spot_tir) else pd.Series(dtype=float))
kisa = int((tir_km < 100).sum()) if len(spot_tir) else 0
bak("Spot tır <100 km hatta çıkmıyor", kisa == 0,
    f"{kisa} spot tır bacağı 100 km altında (o aralıkta Kamyon daha ucuz ve tır iki slot yakar)")

# 2) Tir cok duraklı rota yapiyorsa slot muhasebesi suphesi
tir_bacak_sayisi = tir.groupby("Araç ID").size() if len(tir) else pd.Series(dtype=int)
cok = int((tir_bacak_sayisi > 1).sum()) if len(tir) else 0
bak("Tır çok duraklı rota yapmıyor", cok == 0, f"{cok} tır birden fazla bacak taşıyor")

# 3) TM-gun tir dokunusu kapasiteyi asiyor mu (TM bazinda, havuzlanamaz)
dokunus = {}
for _, g in tir.groupby("Araç ID"):
    s = g.sort_values(["Çıkış Tarihi", "Çıkış Saati"])
    ilk = s.iloc[0]
    dokunus[(ilk[CIKIS], ilk["Çıkış Tarihi"])] = dokunus.get((ilk[CIKIS], ilk["Çıkış Tarihi"]), 0) + 1
    for _, r in s.iterrows():
        dokunus[(r[VARIS], r["Varış Tarihi"])] = dokunus.get((r[VARIS], r["Varış Tarihi"]), 0) + 1
asim = {k: v for k, v in dokunus.items() if v > veri.tir_kapasitesi.get(k[0], 0)}
bak("Hiçbir TM-günde tır slotu aşılmıyor", not asim,
    f"aşan (TM, gün): {sorted(asim.items())[:5]}")

# 4) Konsolidasyon orani
cok_talepli = plan.groupby(["Araç ID", CIKIS, VARIS, "Çıkış Tarihi", "Çıkış Saati"]).size()
oran = 100.0 * (cok_talepli > 1).sum() / len(cok_talepli)
bak(f"Konsolidasyon oranı > %0 (ölçüm: %{oran:.1f})", oran > 0,
    "Hiçbir araç birden fazla talep taşımıyor — ya model çalışmıyor ya elleçleme cezası yanlış")

# 5) Pik gunde DOGAN yukun SLA cezasi sifir olmamali.
#    DIKKAT: cezayi "Cikis Tarihi == pik gun" diye olcmek YANLIS olur — pik gunun
#    tasamayan yuku zaten SONRAKI gunlerde kalkar, cezasi da o satirlara duser.
#    Olculmesi gereken sey yukun DOGDUGU gundur, aracin kalktigi gun degil.
#    (Mimari §10: "bir saglik testinin yanlis olmasi, olmamasindan beterdir".)
pik = config.TAHMIN_BASLANGIC.strftime("%d.%m.%Y")
tahmin = pd.read_excel(cikti / "Talep-tahmini.xlsx")
pik_idler = set(tahmin.loc[tahmin["Tarih"] == pik, "Talep ID"])
plan_kok = plan["Talep ID"].astype(str).str.split("-").str[0]
pik_ceza = plan.loc[plan_kok.isin(pik_idler), "SLA cezası"].sum()
bak(f"Pik günde DOĞAN yükün SLA cezası > 0 (ölçüm: {pik_ceza:,.2f} TL)", pik_ceza > 0,
    "Pik günde 18 TM'nin 17'si elleçleme kapasitesi üstünde; ceza sıfırsa muhasebe şüpheli")

# 6) Arac tipi secimi gercekten en ucuz mu (doluluk basina maliyet)
print("\n=== Araç tipi seçimi: gerçek yükte en ucuz tip seçilmiş mi? ===")
yuk = plan.groupby("Araç ID").agg(
    desi=("Taşınan Desi", "sum"), tur=("Araç türü", "first"),
    tip=("Araç Tipi", "first"), cikis=(CIKIS, "first"), varis=(VARIS, "first"),
    mal=("Toplam maliyet", "sum"))
spot = yuk[yuk["tip"] == "Spot"]


def _en_ucuz(cikis, varis, desi):
    """Bu yuku tasiyabilecek tipler arasinda en ucuzu (tek arac varsayimi)."""
    import math
    en_iyi, en_iyi_mal = None, float("inf")
    for ad, at in veri.arac_tipleri.items():
        if at.kapasite_desi < desi:
            continue
        ell = math.ceil(desi * config.ELLECLEME_DK_PER_DESI - config.TAVAN_TOLERANSI_DK)
        dk = 2 * ell + math.ceil(veri.seyir_saat(cikis, varis, ad) * 60)
        m = at.spot_saatlik_tl * dk / 60.0 + at.spot_km_tl * veri.mesafe_km(cikis, varis)
        if m < en_iyi_mal:
            en_iyi, en_iyi_mal = ad, m
    return en_iyi, en_iyi_mal


kayip = 0.0
yanlis = 0
for arac_id, r in spot.iterrows():
    iyi, iyi_mal = _en_ucuz(r["cikis"], r["varis"], r["desi"])
    if iyi and iyi_mal < r["mal"] - 0.01:
        yanlis += 1
        kayip += r["mal"] - iyi_mal
print(f"  daha ucuz bir araç tipiyle taşınabilecek spot araç: {yanlis} / {len(spot)}")
print(f"  bu seçimlerin toplam fazla maliyeti: {kayip:,.2f} TL")

print(f"\n{'TUM SAGLIK TESTLERI TEMIZ' if uyari == 0 else f'{uyari} SUPHE — arastirilmali'}")
