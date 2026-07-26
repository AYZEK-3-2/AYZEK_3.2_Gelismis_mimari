import pandas as pd
from .simulator import SimulasyonHatasi


# Şablon dosyalarla birebir eşleşmeli
PLAN_SAAT_FORMATI = "SS:DD"       # 09:00, 14:35
TAHMIN_SAAT_FORMATI = "SS:DD:ss"  # 09:00:00, 17:00:00
TARIH_FORMATI = "GG.AA.YYYY"     # 01.04.2026


def dogrula_plan_formati(df: pd.DataFrame) -> None:
    """Tasima-plani.xlsx format kontrolü."""
    # Saat formatı SS:DD olmalı (saniye yok)
    for kolon in ["Çıkış Saati", "Varış Saati"]:
        for deger in df[kolon].dropna().unique():
            s = str(deger)
            if len(s) != 5 or s[2] != ":":
                raise SimulasyonHatasi(
                    f"Plan {kolon} formatı SS:DD olmalı, '{s}' bulundu"
                )

    # Araç Tipi sadece Spot veya Kiralık
    gecersiz_tip = set(df["Araç Tipi"]) - {"Spot", "Kiralık"}
    if gecersiz_tip:
        raise SimulasyonHatasi(f"Geçersiz Araç Tipi: {gecersiz_tip}")

    # Araç türü sadece 4 tip
    gecersiz_tur = set(df["Araç türü"]) - {"Tır", "Kamyon", "Hafif Kamyon", "Kamyonet"}
    if gecersiz_tur:
        raise SimulasyonHatasi(f"Geçersiz Araç türü: {gecersiz_tur}")


def dogrula_muhasebe(df: pd.DataFrame) -> None:
    """Muhasebe invariantı: sütun toplamları bağımsız hesapla eşleşmeli.

    Toplam maliyet aracın ilk satırında, diğerlerinde 0.
    SLA cezası talebin nihai teslim satırında, diğerlerinde 0.
    """
    # Toplam maliyet: her araç için sadece bir satırda değer olmalı
    for arac_id, grup in df.groupby("Araç ID"):
        maliyet_satirlari = grup[grup["Toplam maliyet"] > 0]
        if len(maliyet_satirlari) > 1:
            raise SimulasyonHatasi(
                f"{arac_id} için Toplam maliyet birden fazla satırda yazılmış "
                f"({len(maliyet_satirlari)} satır)"
            )
        if len(maliyet_satirlari) == 0:
            raise SimulasyonHatasi(
                f"{arac_id} için Toplam maliyet hiçbir satırda yok"
            )

    # SLA cezası: aynı Talep ID için en fazla bir satırda (nihai teslim
    # bacağı) değer olmalı — diğer (ara) bacak satırlarında 0. 0'da hiç
    # ceza olmaması NORMALDİR (zamanında teslim); yalnız TEKRAR/ÇOKLU
    # yazım yakalanır.
    for talep_id, grup in df.groupby("Talep ID"):
        ceza_satirlari = grup[grup["SLA cezası"] != 0]
        if len(ceza_satirlari) > 1:
            raise SimulasyonHatasi(
                f"{talep_id} için SLA cezası birden fazla satırda yazılmış "
                f"({len(ceza_satirlari)} satır)"
            )


def dogrula_talep_butunlugu(plan_df: pd.DataFrame, tahmin_df: pd.DataFrame) -> None:
    """Plan ve tahmin dosyasındaki talep ID'leri eşleşmeli.

    Yalnız GERÇEKTEN taşınacak yükü olan (Tahmin Edilen Desi > 0) talepler
    planda karşılık bulmak ZORUNDADIR. `Tahmin-tahmini.xlsx` §3/§8.3 gereği
    0 değerli satırları da içerir (289 hat x 7 gün x 2 slot = tam 4046 satır);
    0 desi öngörülen bir (hat, gün, slot) için fiziksel olarak taşınacak hiçbir
    şey yoktur, o yüzden planda hiç yer almaması beklenen ve doğru bir durumdur
    — bu ayrım yapılmazsa (issue #22 canlı testinde bulundu) tamamen doğru,
    tam kapsamlı bir plan bile "eksik talep" hatasıyla reddedilir.
    """
    plan_kokler = set()
    for tid in plan_df["Talep ID"].unique():
        kok = str(tid).split("-")[0]  # D00001-1 -> D00001
        plan_kokler.add(kok)

    tasinacak = tahmin_df[tahmin_df["Tahmin Edilen Desi"] > 0]
    tahmin_idler = set(tasinacak["Talep ID"].unique())

    eksik = tahmin_idler - plan_kokler
    if eksik:
        raise SimulasyonHatasi(
            f"Tahminde var ama planda eksik talep: {len(eksik)} adet"
        )