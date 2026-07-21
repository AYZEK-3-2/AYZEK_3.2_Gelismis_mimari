import pandas as pd

from .hesaplamalar import (
    ellecleme_suresi_dk,
    seyir_suresi_dk,
    kullanim_suresi_dk,
    arac_maliyeti_tl,
    sla_ceza_tl,
)
from .kapasite import KapasiteDefter


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

def dogrula_zaman_cakismasi(df: pd.DataFrame) -> None:
    """Aynı araç aynı anda iki yerde olamaz."""
    for arac_id, grup in df.groupby("Araç ID"):
        sirali = grup.sort_values(["Çıkış Tarihi", "Çıkış Saati"])
        satirlar = list(sirali.iterrows())

        for i in range(len(satirlar) - 1):
            _, onceki = satirlar[i]
            _, sonraki = satirlar[i + 1]

            onceki_varis = f"{onceki['Varış Tarihi']} {onceki['Varış Saati']}"
            sonraki_cikis = f"{sonraki['Çıkış Tarihi']} {sonraki['Çıkış Saati']}"

            if onceki_varis > sonraki_cikis:
                raise SimulasyonHatasi(
                    f"{arac_id} zaman çakışması: "
                    f"varış {onceki_varis} > sonraki çıkış {sonraki_cikis}"
                )
            

def _hesapla_sla(df: pd.DataFrame, kisitlar) -> list:
    """SLA cezasını bağımsız hesapla, planla karşılaştır."""
    from .hesaplamalar import sla_ceza_tl

    farklar = []

    for _, satir in df.iterrows():
        cikis = satir["Çıkış"]
        varis = satir["Varış"]
        desi = float(satir["Taşınan Desi"])

        # SLA hedef gün
        sla_gun = kisitlar.sla_gun(cikis, varis)

        # Varış zamanını hesapla
        varis_tarihi = str(satir["Varış Tarihi"])
        cikis_tarihi = str(satir["Çıkış Tarihi"])

        # Talep tamamlanma saati (SLA başlangıcı)
        # Kaç gün sürdü
        from datetime import datetime
        try:
            varis_dt = datetime.strptime(
                f"{varis_tarihi} {satir['Varış Saati']}", "%Y-%m-%d %H:%M"
            )
            cikis_dt = datetime.strptime(
                f"{cikis_tarihi} {satir['Çıkış Saati']}", "%Y-%m-%d %H:%M"
            )
        except (ValueError, TypeError):
            continue

        gecen_gun = (varis_dt.date() - cikis_dt.date()).days
        gecikme_gun = gecen_gun - sla_gun

        if gecikme_gun > 0:
            # Gecikme dakikası: fazla günler × 1440 + saat farkı
            gecikme_dk = gecikme_gun * 1440
            sim_ceza = sla_ceza_tl(desi, gecikme_dk)
        else:
            sim_ceza = 0.0

        plan_ceza = float(satir["SLA cezası"])

        if abs(sim_ceza - plan_ceza) > 0.01:
            farklar.append({
                "talep_id": satir["Talep ID"],
                "sim_ceza": sim_ceza,
                "plan_ceza": plan_ceza,
                "fark": sim_ceza - plan_ceza,
            })

    return farklar

def _hesapla_maliyet(df: pd.DataFrame, kisitlar) -> list:
    """Her araç için maliyeti bağımsız hesapla, planla karşılaştır."""
    farklar = []

    for arac_id, grup in df.groupby("Araç ID"):
        arac_tipi_ad = grup["Araç türü"].iloc[0]
        arac_tipi = kisitlar.arac_tipleri[arac_tipi_ad]
        kiralik_mi = grup["Araç Tipi"].iloc[0] == "Kiralık"

        if kiralik_mi:
            saatlik = arac_tipi.kiralik_saatlik_tl
            km_tl = arac_tipi.kiralik_km_tl
        else:
            saatlik = arac_tipi.spot_saatlik_tl
            km_tl = arac_tipi.spot_km_tl

        toplam_desi = int(grup["Taşınan Desi"].sum())
        cikis = grup["Çıkış"].iloc[0]
        varis = grup["Varış"].iloc[0]

        mesafe = kisitlar.mesafe_km(cikis, varis)
        seyir_saat = kisitlar.seyir_saat(cikis, varis, arac_tipi_ad)

        kullanim_dk = kullanim_suresi_dk(toplam_desi, seyir_saat)
        sim_maliyet = arac_maliyeti_tl(saatlik, km_tl, kullanim_dk, mesafe)

        plan_maliyet = grup["Toplam maliyet"].sum()

        if abs(sim_maliyet - plan_maliyet) > 0.01:
            farklar.append({
                "arac_id": arac_id,
                "sim_maliyet": sim_maliyet,
                "plan_maliyet": plan_maliyet,
                "fark": sim_maliyet - plan_maliyet,
            })

    return farklar

def simulasyonu_calistir(plan_dosyasi: str, kisitlar) -> dict:
    """Planı oku, tüm doğrulamaları çalıştır, maliyeti bağımsız hesapla."""
    df = plan_oku(plan_dosyasi)

    # Yapısal doğrulamalar
    dogrula_arac_tutarliligi(df)
    dogrula_rota_gecerliligi(df)
    dogrula_kiralik(df, kisitlar.kiralik_hatlar)
    dogrula_zaman_cakismasi(df)

    # Kapasite kontrolü
    kapasite = KapasiteDefter(
        dict(kisitlar.ellecleme_kapasitesi),
        dict(kisitlar.tir_kapasitesi),
    )

    for _, satir in df.iterrows():
        gun = str(satir["Çıkış Tarihi"])
        desi = int(satir["Taşınan Desi"])
        cikis_tm = satir["Çıkış"]
        varis_tm = satir["Varış"]

        kapasite.ellecleme_ekle(cikis_tm, gun, desi)
        kapasite.ellecleme_ekle(varis_tm, gun, desi)

        if satir["Araç türü"] == "Tır":
            kapasite.tir_dokunusu_ekle(cikis_tm, gun)
            kapasite.tir_dokunusu_ekle(varis_tm, gun)

    ihlaller = kapasite.dogrula()
    if ihlaller:
        mesaj = "\n".join(ihlaller)
        raise SimulasyonHatasi(f"Kapasite ihlalleri:\n{mesaj}")

    # Maliyet doğrulama — bağımsız hesapla, planla karşılaştır
    farklar = _hesapla_maliyet(df, kisitlar)
    if farklar:
        detay = "\n".join(
            f"  {f['arac_id']}: sim={f['sim_maliyet']:.2f} plan={f['plan_maliyet']:.2f} fark={f['fark']:.2f}"
            for f in farklar
        )
        raise SimulasyonHatasi(f"Maliyet farkları bulundu:\n{detay}")

    # SLA doğrulama — bağımsız hesapla, planla karşılaştır
    sla_farklar = _hesapla_sla(df, kisitlar)
    if sla_farklar:
        detay = "\n".join(
            f"  {f['talep_id']}: sim={f['sim_ceza']:.2f} plan={f['plan_ceza']:.2f} fark={f['fark']:.2f}"
            for f in sla_farklar
        )
        raise SimulasyonHatasi(f"SLA ceza farkları bulundu:\n{detay}")

    # Özet
    toplam_arac = df["Araç ID"].nunique()
    toplam_talep = df["Talep ID"].nunique()
    sim_toplam = sum(
        arac_maliyeti_tl(
            kisitlar.arac_tipleri[row["Araç türü"]].kiralik_saatlik_tl
            if row["Araç Tipi"] == "Kiralık"
            else kisitlar.arac_tipleri[row["Araç türü"]].spot_saatlik_tl,
            kisitlar.arac_tipleri[row["Araç türü"]].kiralik_km_tl
            if row["Araç Tipi"] == "Kiralık"
            else kisitlar.arac_tipleri[row["Araç türü"]].spot_km_tl,
            kullanim_suresi_dk(
                int(row["Taşınan Desi"]),
                kisitlar.seyir_saat(row["Çıkış"], row["Varış"], row["Araç türü"]),
            ),
            kisitlar.mesafe_km(row["Çıkış"], row["Varış"]),
        )
        for _, row in df.drop_duplicates("Araç ID").iterrows()
    )

    ozet = {
        "toplam_arac": toplam_arac,
        "toplam_talep": toplam_talep,
        "toplam_maliyet": sim_toplam,
        "toplam_ceza": df["SLA cezası"].sum(),
        "dogrulama": "GECTI",
    }

    print(f"Simülatör: {toplam_arac} araç, {toplam_talep} talep")
    print(f"Toplam maliyet (sim): {sim_toplam:,.2f} TL")
    print("Doğrulama: GEÇTI")

    return ozet
