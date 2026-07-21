import pandas as pd


# Tasima-plani.xlsx'teki beklenen sütunlar
PLAN_SUTUNLARI = [
    "Araç ID", "Araç Tipi", "Araç türü",
    "Çıkış", "Varış",
    "Çıkış Tarihi", "Çıkış Saati",
    "Varış Tarihi", "Varış Saati",
    "Talep ID", "Taşınan Desi",
    "Yolculuk süresi",
    "Çıkış elleçleme süresi", "Varış elleçleme süresi",
    "Toplam maliyet", "SLA cezası",
]


class SimulasyonHatasi(Exception):
    """Plan doğrulamada bulunan hata."""
    pass


def plan_oku(dosya_yolu: str) -> pd.DataFrame:
    """Tasima-plani.xlsx dosyasını okur ve sütun kontrolü yapar."""
    df = pd.read_excel(dosya_yolu)

    # Sütun kontrolü
    eksik = set(PLAN_SUTUNLARI) - set(df.columns)
    fazla = set(df.columns) - set(PLAN_SUTUNLARI)
    if eksik:
        raise SimulasyonHatasi(f"Planda eksik sütunlar: {sorted(eksik)}")
    if fazla:
        raise SimulasyonHatasi(f"Planda fazla sütunlar: {sorted(fazla)}")

    if df.empty:
        raise SimulasyonHatasi("Plan dosyası boş.")

    return df

def dogrula_arac_tutarliligi(df: pd.DataFrame) -> None:
    """Her Araç ID tek bir araç türü ve tek bir tip taşımalı."""
    for arac_id, grup in df.groupby("Araç ID"):
        turleri = grup["Araç türü"].unique()
        if len(turleri) > 1:
            raise SimulasyonHatasi(
                f"{arac_id} birden fazla araç türü taşıyor: {list(turleri)}"
            )
        tipleri = grup["Araç Tipi"].unique()
        if len(tipleri) > 1:
            raise SimulasyonHatasi(
                f"{arac_id} birden fazla araç tipi taşıyor: {list(tipleri)}"
            )


def dogrula_rota_gecerliligi(df: pd.DataFrame) -> None:
    """Her talebin bindiği araç, çıkış TM'sini varış TM'sinden ÖNCE ziyaret etmeli."""
    for arac_id, grup in df.groupby("Araç ID"):
        # Aracın ziyaret ettiği TM'leri sırayla al
        duraklar = []
        for _, satir in grup.iterrows():
            if satir["Çıkış"] not in duraklar:
                duraklar.append(satir["Çıkış"])
            if satir["Varış"] not in duraklar:
                duraklar.append(satir["Varış"])

        # Her talep için çıkış varıştan önce mi kontrol et
        for _, satir in grup.iterrows():
            talep_cikis = satir["Çıkış"]
            talep_varis = satir["Varış"]
            cikis_idx = duraklar.index(talep_cikis)
            varis_idx = duraklar.index(talep_varis)
            if cikis_idx >= varis_idx:
                raise SimulasyonHatasi(
                    f"{arac_id} rotasında {satir['Talep ID']} için "
                    f"{talep_cikis} -> {talep_varis} sırası yanlış. "
                    f"Rota: {duraklar}"
                )
            

def dogrula_kiralik(df: pd.DataFrame, kiralik_hatlar) -> None:
    """12 kiralık araç her gün kendi hattında çıkmış mı kontrol et."""
    kiralik_satirlar = df[df["Araç Tipi"] == "Kiralık"]

    for kiralik in kiralik_hatlar:
        eslesme = kiralik_satirlar[
            (kiralik_satirlar["Çıkış"] == kiralik.cikis)
            & (kiralik_satirlar["Varış"] == kiralik.varis)
            & (kiralik_satirlar["Araç türü"] == kiralik.arac_turu)
        ]
        if eslesme.empty:
            raise SimulasyonHatasi(
                f"Kiralık araç eksik: {kiralik.cikis} -> {kiralik.varis} "
                f"({kiralik.arac_turu}, {kiralik.adet} adet)"
            )


def simulasyonu_calistir(plan_dosyasi: str, kisitlar) -> dict:
    """Planı oku, tüm doğrulamaları çalıştır, sonuçları döndür."""
    df = plan_oku(plan_dosyasi)

    # Doğrulamalar
    dogrula_arac_tutarliligi(df)
    dogrula_rota_gecerliligi(df)
    dogrula_kiralik(df, kisitlar.kiralik_hatlar)

    # Özet bilgiler
    toplam_arac = df["Araç ID"].nunique()
    toplam_talep = df["Talep ID"].nunique()
    toplam_maliyet = df["Toplam maliyet"].sum()
    toplam_ceza = df["SLA cezası"].sum()

    ozet = {
        "toplam_arac": toplam_arac,
        "toplam_talep": toplam_talep,
        "toplam_maliyet": toplam_maliyet,
        "toplam_ceza": toplam_ceza,
        "dogrulama": "GECTI",
    }

    print(f"Simülatör: {toplam_arac} araç, {toplam_talep} talep")
    print(f"Toplam maliyet: {toplam_maliyet:,.2f} TL")
    print(f"SLA cezası: {toplam_ceza:,.2f} TL")
    print("Doğrulama: GEÇTI")

    return ozet

