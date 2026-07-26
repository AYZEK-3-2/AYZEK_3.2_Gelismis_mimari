# -*- coding: utf-8 -*-
"""Teslim provasi: cikti dosyalarini juri sablonlariyla ve sartname kurallariyla
karsilastirir.

Kullanim:  python scripts/teslim_provasi.py cikti/

Sartnamenin "bu formata uymayan takimlarin sonuclari kesinlikle degerlendirmeye
alinmayacaktir" maddesi teslimdeki tek diskalifiye sebebidir; bu betik teslim
oncesi son kontroldur. Hata bulursa sifirdan farkli exit code doner.

Not: `katman3_simulator` kapilari zaten her kosuda calisir; bu betik onlarin
DISINDA, teslim edilecek DOSYALAR uzerinden bagimsiz bir ikinci goz olarak
tasarlandi (kapinin kendisi bozulursa yakalayan sey budur).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

cikti = Path(sys.argv[1])
sablon = config.SABLON_KLASORU

hata = 0


def kontrol(ad, kosul, detay=""):
    global hata
    if kosul:
        print(f"  [OK]  {ad}")
    else:
        hata += 1
        print(f"  [HATA] {ad} {detay}")


for dosya, sab in (("Talep-tahmini.xlsx", "TALEP_TAHMINI_sablon.xlsx"),
                   ("Tasima-plani.xlsx", "TASIMA_PLANI_sablon.xlsx")):
    print(f"\n=== {dosya} ===")
    df = pd.read_excel(cikti / dosya)
    sdf = pd.read_excel(sablon / sab)
    kontrol("sutun adlari ve sirasi sablonla birebir",
            list(df.columns) == list(sdf.columns),
            f"\n    cikti : {list(df.columns)}\n    sablon: {list(sdf.columns)}")
    print(f"  satir: {len(df)}")

# Talep-tahmini ozel kurallar
t = pd.read_excel(cikti / "Talep-tahmini.xlsx")
print("\n=== Talep-tahmini kurallari (sartname) ===")
kontrol("TAM 4046 satir", len(t) == 4046, f"({len(t)})")
kontrol("Tarih GG.AA.YYYY metin",
        t["Tarih"].map(lambda v: isinstance(v, str) and len(v) == 10 and v[2] == "." and v[5] == ".").all())
kontrol("Saat SS:DD:ss metin",
        t["Talep Tamamlama Saati"].map(lambda v: isinstance(v, str) and len(v) == 8).all())
kontrol("yalniz 09:00:00 / 17:00:00",
        set(t["Talep Tamamlama Saati"]) == {"09:00:00", "17:00:00"})
kontrol("dusuk degerli (<0,5) satirlar da var (filtrelenmemis)",
        (t["Tahmin Edilen Desi"] < 0.5).any(),
        f"(<0,5 satir: {(t['Tahmin Edilen Desi'] < 0.5).sum()})")
kontrol("negatif tahmin yok", (t["Tahmin Edilen Desi"] >= 0).all())
kontrol("Talep ID tekil", t["Talep ID"].is_unique)

# Tasima-plani ozel kurallar
p = pd.read_excel(cikti / "Tasima-plani.xlsx")
print("\n=== Tasima-plani kurallari (sartname) ===")
kontrol("Tarih GG.AA.YYYY metin",
        p["Çıkış Tarihi"].map(lambda v: isinstance(v, str) and len(v) == 10).all())
kontrol("Saat SS:DD metin (saniyesiz — tahmin dosyasindan FARKLI)",
        p["Çıkış Saati"].map(lambda v: isinstance(v, str) and len(v) == 5).all())
kontrol("Arac Tipi in {Spot, Kiralık}", set(p["Araç Tipi"]) <= {"Spot", "Kiralık"})
kontrol("Arac turu 4 tipten",
        set(p["Araç türü"]) <= {"Tır", "Kamyon", "Hafif Kamyon", "Kamyonet"})

# ID esleme: plan koklerinin tamami tahmin dosyasinda olmali
kok = set(p["Talep ID"].astype(str).str.split("-").str[0])
tid = set(t["Talep ID"])
kontrol("plan ID kokleri tahmin dosyasinda var", kok <= tid,
        f"(fazlalik: {sorted(kok - tid)[:5]})")
tasinacak = set(t.loc[t["Tahmin Edilen Desi"] > 0, "Talep ID"])
kontrol("tasinacak her talep planda var", tasinacak <= kok,
        f"(eksik: {len(tasinacak - kok)})")

# Muhasebe invarianti
print("\n=== Muhasebe invarianti (§8.2) ===")
mal = p.groupby("Araç ID")["Toplam maliyet"].apply(lambda s: (s > 0).sum())
kontrol("Toplam maliyet arac basina TEK satirda", (mal <= 1).all(),
        f"({(mal > 1).sum()} arac cok satirli)")
kontrol("her aracin maliyeti var", (mal == 1).all(), f"({(mal == 0).sum()} arac maliyetsiz)")
sla = p.groupby("Talep ID")["SLA cezası"].apply(lambda s: (s != 0).sum())
kontrol("SLA cezasi talep basina en fazla TEK satirda", (sla <= 1).all())

# Desi korunumu
print("\n=== Desi korunumu ===")
kontrol("plan tasinan desi == tahmin toplam desi",
        abs(p["Taşınan Desi"].sum() - t["Tahmin Edilen Desi"].sum()) < 1.0,
        f"(plan {p['Taşınan Desi'].sum():,.1f} vs tahmin {t['Tahmin Edilen Desi'].sum():,.1f})")

print(f"\n{'TESLIM PROVASI GECTI' if hata == 0 else f'{hata} HATA VAR'}")
sys.exit(1 if hata else 0)
