# -*- coding: utf-8 -*-
"""Excel okuyucular, yükleme-anı doğrulama ve kısıt nesnesi kurulumu.

Tasarım ilkeleri
----------------
* Beklenmedik kolon / eksik dosya / bozuk değerde **sessiz devam yok** —
  `VeriHatasi` ile açıklayıcı biçimde durulur.
* Yalnız *yapısal* doğrulama yapılır (tutarlılık, tip, aralık, boşluk).
  "Toplam tır slotu 69", "7 sıfır-TM" gibi veriye özgü sayılar buraya
  gömülmez; jüri kapasiteleri güncelleyebilir (mimari §12). Onlar teslim
  kapısı değil, testlerdeki regresyon kontrolüdür.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config

from .kisitlar import (
    ARAC_ADLARI,
    AracTipi,
    Kisitlar,
    KiralikHat,
    _read_only,
)


class VeriHatasi(Exception):
    """Yükleme sırasında bir dosya beklenen sözleşmeyi karşılamadığında atılır."""


# Her dosyanın beklenen sütun kümesi (fazlası da eksiği de hata).
_BEKLENEN_KOLONLAR = {
    "teknofest26_gelismis.xlsx": {
        "tarih", "cikis", "varis", "talep_id", "toplam_desi", "talep_tamamlanma_saati",
    },
    "sehirler_arasi_lojistik.xlsx": {
        "cikis", "varis", "mesafe_km", "Tir_Suresi_Saat", "Kamyon_Suresi_Saat",
        "Hafif_Kamyon_Suresi_Saat", "Kamyonet_Suresi_Saat", "hedef_teslim_gun",
    },
    "tir_kapasiteleri_v2.xlsx": {"transfer_merkezi", "tir_kapasitesi"},
    "ellecleme_kapasite.xlsx": {"transfer_merkezi", "ellecleme_kapasite"},
    "kiralik_araclar.xlsx": {
        "Çıkış Transfer Merkezi", "Varış Transfer Merkezi", "Araç sayısı", "Araç Türü",
    },
    "arac_kapasite_maliyet_saat.xlsx": {
        "Araç Adı", "Kapasite (desi)", "Kiralık Araç Saatlik Kira (TL)",
        "Kiralık Araç Kilometre Başına Maliyet (TL)", "Spot Araç Saatlik Kira (TL)",
        "Spot Kilometre Başına Maliyet (TL)",
    },
}

# lojistik matrisindeki süre sütunu -> kanonik araç adı
_SEYIR_KOLON = {
    "Tir_Suresi_Saat": "Tır",
    "Kamyon_Suresi_Saat": "Kamyon",
    "Hafif_Kamyon_Suresi_Saat": "Hafif Kamyon",
    "Kamyonet_Suresi_Saat": "Kamyonet",
}

# ham slot -> kanonik slot (veri '9:00', çıktı/format '09:00')
_SLOT_NORMAL = {"9:00": "09:00", "09:00": "09:00", "17:00": "17:00"}


def _oku(veri_klasoru: Path, dosya: str) -> pd.DataFrame:
    """Bir excel'i okur ve sütun sözleşmesini doğrular."""
    yol = veri_klasoru / dosya
    if not yol.exists():
        raise VeriHatasi(f"Veri dosyası bulunamadı: {yol}")
    try:
        df = pd.read_excel(yol)
    except Exception as e:  # noqa: BLE001 - kaynak ne olursa olsun net mesaj
        raise VeriHatasi(f"{dosya} okunamadı: {e}") from e

    beklenen = _BEKLENEN_KOLONLAR[dosya]
    var = set(df.columns)
    if var != beklenen:
        eksik = beklenen - var
        fazla = var - beklenen
        raise VeriHatasi(
            f"{dosya} sütunları beklenenle uyuşmuyor. "
            f"Eksik: {sorted(eksik) or '-'} | Fazla: {sorted(fazla) or '-'}"
        )
    if df.empty:
        raise VeriHatasi(f"{dosya} boş.")
    return df


def _hata_yoksa(kosul: bool, mesaj: str) -> None:
    if not kosul:
        raise VeriHatasi(mesaj)


# --- tekil doğrulayıcılar (testlerden doğrudan çağrılabilsin diye ayrık) -----

def dogrula_talep(df: pd.DataFrame) -> None:
    _hata_yoksa(not df.isna().any().any(), "teknofest26_gelismis.xlsx içinde boş hücre var.")
    _hata_yoksa((df["toplam_desi"] > 0).all(), "toplam_desi sıfır veya negatif satır içeriyor.")
    _hata_yoksa(
        pd.api.types.is_integer_dtype(df["toplam_desi"]),
        "toplam_desi tamsayı değil.",
    )
    gecersiz_slot = set(df["talep_tamamlanma_saati"].astype(str)) - set(_SLOT_NORMAL)
    _hata_yoksa(not gecersiz_slot, f"Beklenmeyen talep saati: {gecersiz_slot}")
    tarih = pd.to_datetime(df["tarih"])
    _hata_yoksa(
        tarih.min() >= pd.Timestamp("2026-01-01") and tarih.max() <= pd.Timestamp("2026-06-28"),
        f"Talep tarihleri 01.01–28.06.2026 dışında: {tarih.min().date()}–{tarih.max().date()}",
    )


def dogrula_lojistik(df: pd.DataFrame) -> None:
    _hata_yoksa(not df.isna().any().any(), "sehirler_arasi_lojistik.xlsx içinde boş hücre var.")
    _hata_yoksa(not df.duplicated(["cikis", "varis"]).any(), "Lojistik matrisinde tekrar eden yönlü çift var.")
    _hata_yoksa((df["cikis"] != df["varis"]).all(), "Lojistik matrisinde self-loop (aynı TM) var.")
    _hata_yoksa((df["mesafe_km"] > 0).all(), "mesafe_km sıfır/negatif değer içeriyor.")
    _hata_yoksa(set(df["hedef_teslim_gun"]) <= {1, 2}, "hedef_teslim_gun 1/2 dışında değer içeriyor.")
    for kol in _SEYIR_KOLON:
        _hata_yoksa((df[kol] > 0).all(), f"{kol} sıfır/negatif seyir süresi içeriyor.")


def dogrula_tm_tutarlilik(
    tms_talep: set, tms_loj: set, tms_tir: set, tms_ell: set, tms_kir: set
) -> tuple[str, ...]:
    """Altı dosyadaki TM kümelerinin tutarlılığını doğrular, kanonik listeyi döndürür."""
    _hata_yoksa(
        tms_talep == tms_loj == tms_tir == tms_ell,
        "TM kümeleri dosyalar arasında tutarsız "
        f"(talep={len(tms_talep)}, loj={len(tms_loj)}, tir={len(tms_tir)}, ell={len(tms_ell)}). "
        f"talep∖tir={sorted(tms_talep - tms_tir)}, tir∖talep={sorted(tms_tir - tms_talep)}",
    )
    _hata_yoksa(
        tms_kir <= tms_tir,
        f"Kiralık araç TM'leri bilinen küme dışında: {sorted(tms_kir - tms_tir)}",
    )
    return tuple(sorted(tms_tir))


# --- ana giriş ----------------------------------------------------------------

def veriyi_yukle(veri_klasoru: Path | None = None) -> Kisitlar:
    """Altı excel'i okur, doğrular ve değişmez `Kisitlar` nesnesini kurar."""
    kok = Path(veri_klasoru) if veri_klasoru is not None else config.VERI_KLASORU

    talep = _oku(kok, "teknofest26_gelismis.xlsx")
    loj = _oku(kok, "sehirler_arasi_lojistik.xlsx")
    tir = _oku(kok, "tir_kapasiteleri_v2.xlsx")
    ell = _oku(kok, "ellecleme_kapasite.xlsx")
    kir = _oku(kok, "kiralik_araclar.xlsx")
    arac = _oku(kok, "arac_kapasite_maliyet_saat.xlsx")

    # dosya-içi doğrulama
    dogrula_talep(talep)
    dogrula_lojistik(loj)
    _hata_yoksa(not tir.duplicated("transfer_merkezi").any(), "tır kapasitesinde tekrar eden TM var.")
    _hata_yoksa((tir["tir_kapasitesi"] >= 0).all(), "tır kapasitesi negatif değer içeriyor.")
    _hata_yoksa(not ell.duplicated("transfer_merkezi").any(), "elleçleme kapasitesinde tekrar eden TM var.")
    _hata_yoksa((ell["ellecleme_kapasite"] > 0).all(), "elleçleme kapasitesi sıfır/negatif değer içeriyor.")
    _hata_yoksa(
        set(arac["Araç Adı"]) == set(ARAC_ADLARI),
        f"Araç adları beklenenle uyuşmuyor: {sorted(set(arac['Araç Adı']))}",
    )
    _hata_yoksa(
        set(kir["Araç Türü"]) <= set(ARAC_ADLARI),
        f"Kiralık araç türü bilinmiyor: {sorted(set(kir['Araç Türü']) - set(ARAC_ADLARI))}",
    )
    _hata_yoksa((kir["Araç sayısı"] > 0).all(), "Kiralık araç sayısı sıfır/negatif.")

    # TM tutarlılığı (dosyalar arası)
    tms_talep = set(talep["cikis"]) | set(talep["varis"])
    tms_loj = set(loj["cikis"]) | set(loj["varis"])
    tms_kir = set(kir["Çıkış Transfer Merkezi"]) | set(kir["Varış Transfer Merkezi"])
    transfer_merkezleri = dogrula_tm_tutarlilik(
        tms_talep, tms_loj, set(tir["transfer_merkezi"]), set(ell["transfer_merkezi"]), tms_kir
    )

    # her talep hattı lojistik matrisinde olmalı (mesafe/SLA'sı bulunsun)
    talep_hatlar = set(map(tuple, talep[["cikis", "varis"]].drop_duplicates().to_numpy()))
    loj_hatlar = set(map(tuple, loj[["cikis", "varis"]].to_numpy()))
    _hata_yoksa(
        talep_hatlar <= loj_hatlar,
        f"Lojistik matrisinde karşılığı olmayan talep hattı: {sorted(talep_hatlar - loj_hatlar)}",
    )

    # --- kısıt nesnelerini kur ---
    arac_tipleri = {
        r["Araç Adı"]: AracTipi(
            ad=r["Araç Adı"],
            kapasite_desi=int(r["Kapasite (desi)"]),
            kiralik_saatlik_tl=float(r["Kiralık Araç Saatlik Kira (TL)"]),
            kiralik_km_tl=float(r["Kiralık Araç Kilometre Başına Maliyet (TL)"]),
            spot_saatlik_tl=float(r["Spot Araç Saatlik Kira (TL)"]),
            spot_km_tl=float(r["Spot Kilometre Başına Maliyet (TL)"]),
        )
        for _, r in arac.iterrows()
    }

    mesafe_km, sla_gun, seyir_saat = {}, {}, {}
    for _, r in loj.iterrows():
        anahtar = (r["cikis"], r["varis"])
        mesafe_km[anahtar] = int(r["mesafe_km"])
        sla_gun[anahtar] = int(r["hedef_teslim_gun"])
        for kol, arac_ad in _SEYIR_KOLON.items():
            seyir_saat[(r["cikis"], r["varis"], arac_ad)] = float(r[kol])

    tir_kapasitesi = {r["transfer_merkezi"]: int(r["tir_kapasitesi"]) for _, r in tir.iterrows()}
    ellecleme_kapasitesi = {r["transfer_merkezi"]: float(r["ellecleme_kapasite"]) for _, r in ell.iterrows()}

    kiralik_hatlar = tuple(
        KiralikHat(
            cikis=r["Çıkış Transfer Merkezi"],
            varis=r["Varış Transfer Merkezi"],
            arac_turu=r["Araç Türü"],
            adet=int(r["Araç sayısı"]),
        )
        for _, r in kir.iterrows()
    )

    # talep tablosunu normalize et: slot '9:00' -> '09:00', tarih datetime
    talep = talep.copy()
    talep["tarih"] = pd.to_datetime(talep["tarih"])
    talep["slot"] = talep["talep_tamamlanma_saati"].astype(str).map(_SLOT_NORMAL)
    talep = talep.reset_index(drop=True)

    aktif_hatlar = tuple(sorted(talep_hatlar))

    return Kisitlar(
        transfer_merkezleri=transfer_merkezleri,
        aktif_hatlar=aktif_hatlar,
        arac_tipleri=_read_only(arac_tipleri),
        tir_kapasitesi=_read_only(tir_kapasitesi),
        ellecleme_kapasitesi=_read_only(ellecleme_kapasitesi),
        kiralik_hatlar=kiralik_hatlar,
        _mesafe_km=_read_only(mesafe_km),
        _sla_gun=_read_only(sla_gun),
        _seyir_saat=_read_only(seyir_saat),
        talep=talep,
    )
