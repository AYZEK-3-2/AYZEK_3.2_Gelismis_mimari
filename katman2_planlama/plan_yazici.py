# -*- coding: utf-8 -*-
"""Tasima-plani.xlsx yazıcısı (Issue #16).

Satır birimi: (Araç ID, bacak, Talep ID).
Muhasebe invariantı:
  Toplam maliyet  → aracın ilk satırı, diğerleri 0
  SLA cezası      → talebin son_bacak=True satırı, diğerleri 0
  Yolculuk + elleçleme süreleri → bacağın ilk talep satırı, diğerleri 0
  Taşınan Desi    → her satırda kendi değeri
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

SABLON_SUTUNLARI = [
    "Araç ID", "Araç Tipi", "Araç türü",
    "Çıkış", "Varış",
    "Çıkış Tarihi", "Çıkış Saati",
    "Varış Tarihi", "Varış Saati",
    "Talep ID", "Taşınan Desi",
    "Yolculuk süresi",
    "Çıkış elleçleme süresi", "Varış elleçleme süresi",
    "Toplam maliyet", "SLA cezası",
]


@dataclass
class TalepAtama:
    """Bir talebin tek bacaktaki bilgisi."""
    talep_id: str
    desi: float
    son_bacak: bool   # bu bacak talebin teslim bacağı mı?
    sla_ceza: float   # son_bacak=True → hesaplanmış ceza, diğerleri 0.0


@dataclass
class BacakAtama:
    """Bir araç bacağındaki yük ve zamanlama."""
    cikis: str
    varis: str
    cikis_ani: datetime   # hareket anı (yükleme bittikten sonra)
    varis_ani: datetime   # teslim anı (varış elleçleme bittikten sonra)
    seyir_dk: int         # yalnız seyir süresi (elleçleme hariç)
    talepler: list[TalepAtama]


@dataclass
class AracPlan:
    """Tek aracın tüm hareket planı."""
    arac_tipi: str    # "Tır" | "Kamyon" | "Hafif Kamyon" | "Kamyonet"
    kiralik: bool
    bacaklar: list[BacakAtama]
    toplam_maliyet: float


def plan_yaz(
    arac_planlari: list[AracPlan],
    dosya_yolu: str | None = None,
) -> pd.DataFrame:
    """Araç planlarını şablon formatına dönüştürür; dosya_yolu verilirse yazar.

    Döndürür: oluşturulan plan DataFrame'i.
    """
    satirlar: list[dict] = []

    for arac_idx, arac in enumerate(arac_planlari):
        arac_id = f"V{arac_idx + 1:04d}"
        arac_tipi_str = "Kiralık" if arac.kiralik else "Spot"
        arac_ilk_satir = True

        for bacak in arac.bacaklar:
            toplam_desi = sum(t.desi for t in bacak.talepler)
            ell_dk = math.ceil(toplam_desi * 0.01)
            bacak_ilk_satir = True

            for talep in bacak.talepler:
                satirlar.append({
                    "Araç ID": arac_id,
                    "Araç Tipi": arac_tipi_str,
                    "Araç türü": arac.arac_tipi,
                    "Çıkış": bacak.cikis,
                    "Varış": bacak.varis,
                    "Çıkış Tarihi": bacak.cikis_ani.strftime("%d.%m.%Y"),
                    "Çıkış Saati": bacak.cikis_ani.strftime("%H:%M"),
                    "Varış Tarihi": bacak.varis_ani.strftime("%d.%m.%Y"),
                    "Varış Saati": bacak.varis_ani.strftime("%H:%M"),
                    "Talep ID": talep.talep_id,
                    "Taşınan Desi": talep.desi,
                    "Yolculuk süresi": bacak.seyir_dk if bacak_ilk_satir else 0,
                    "Çıkış elleçleme süresi": ell_dk if bacak_ilk_satir else 0,
                    "Varış elleçleme süresi": ell_dk if bacak_ilk_satir else 0,
                    "Toplam maliyet": arac.toplam_maliyet if arac_ilk_satir else 0.0,
                    "SLA cezası": talep.sla_ceza if talep.son_bacak else 0.0,
                })
                arac_ilk_satir = False
                bacak_ilk_satir = False

    df = pd.DataFrame(satirlar, columns=SABLON_SUTUNLARI)

    if dosya_yolu:
        df.to_excel(dosya_yolu, index=False)

    return df