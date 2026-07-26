import pandas as pd
from datetime import datetime, timedelta

from .hesaplamalar import (
    ellecleme_suresi_dk,
    seyir_suresi_dk,
    kullanim_suresi_dk,
    arac_maliyeti_tl,
    sla_ceza_tl,
    gece_yarisi_bolme,
)
from .kapasite import KapasiteDefter


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


def _tarihe_cevir(tarih, saat):
    """Tarih + saat bilgisini datetime nesnesine çevirir.

    Tarih pandas Timestamp, datetime veya string olabilir.
    String ise GG.AA.YYYY veya YYYY-MM-DD formatında olabilir.
    """
    if isinstance(tarih, (pd.Timestamp, datetime)):
        dt = tarih if isinstance(tarih, datetime) else tarih.to_pydatetime()
        saat_str = str(saat)
        s, d = map(int, saat_str.split(":"))
        return dt.replace(hour=s, minute=d, second=0, microsecond=0)

    tarih_str = str(tarih)
    saat_str = str(saat)
    for fmt in ["%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"]:
        try:
            return datetime.strptime(f"{tarih_str} {saat_str}", fmt)
        except ValueError:
            continue
    raise SimulasyonHatasi(f"Tarih parse edilemedi: {tarih_str} {saat_str}")


def _gun_str(tarih):
    """Tarih bilgisini tutarlı string'e çevirir (kapasite anahtarı için)."""
    if isinstance(tarih, (pd.Timestamp, datetime)):
        return tarih.strftime("%Y-%m-%d")
    return str(tarih)


def plan_oku(dosya_yolu: str) -> pd.DataFrame:
    """Tasima-plani.xlsx dosyasını okur ve sütun kontrolü yapar."""
    df = pd.read_excel(dosya_yolu)
    
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
        sirali = grup.sort_values(["Çıkış Tarihi", "Çıkış Saati"])

        duraklar = []
        for _, satir in sirali.iterrows():
            if satir["Çıkış"] not in duraklar:
                duraklar.append(satir["Çıkış"])
            if satir["Varış"] not in duraklar:
                duraklar.append(satir["Varış"])

        for _, satir in sirali.iterrows():
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
    """Aynı araç aynı anda iki yerde olamaz.

    Satır birimi (Araç ID, bacak, Talep ID) olduğu için tek bir bacak birden fazla
    satır (birden fazla Talep ID) içerebilir — konsolidasyonda normal ve beklenen
    durum. Bu yüzden önce BACAK bazında (Çıkış, Varış, Çıkış Tarihi, Çıkış Saati)
    tekilleştirilir; aksi halde bir bacağın kendi varışı, aynı bacağın başka bir
    talep satırındaki (aynı) çıkışıyla yanlışlıkla "çakışma" sayılır.
    """
    for arac_id, grup in df.groupby("Araç ID"):
        bacaklar = grup.drop_duplicates(
            subset=["Çıkış", "Varış", "Çıkış Tarihi", "Çıkış Saati", "Varış Tarihi", "Varış Saati"]
        )
        sirali = bacaklar.sort_values(["Çıkış Tarihi", "Çıkış Saati"])
        satirlar = list(sirali.iterrows())

        for i in range(len(satirlar) - 1):
            _, onceki = satirlar[i]
            _, sonraki = satirlar[i + 1]

            onceki_varis = _tarihe_cevir(
                onceki["Varış Tarihi"], onceki["Varış Saati"]
            )
            sonraki_cikis = _tarihe_cevir(
                sonraki["Çıkış Tarihi"], sonraki["Çıkış Saati"]
            )

            if onceki_varis > sonraki_cikis:
                raise SimulasyonHatasi(
                    f"{arac_id} zaman çakışması: "
                    f"varış {onceki_varis} > sonraki çıkış {sonraki_cikis}"
                )


def dogrula_dogus_ani(df: pd.DataFrame, kisitlar) -> None:
    """Hiçbir araç, taşıdığı yük DOĞMADAN önce kalkmış olamaz.

    Bir talep ancak kendi tamamlanma anında (09:00 / 17:00) var olur; o andan
    önce kalkan bir araca yüklenmesi fiziksel olarak imkânsızdır. Bu kontrol
    hiç yoktu ve hiçbir kapı yerini tutmuyordu: rota geçerliliği yalnız durak
    SIRASINA, zaman çakışması yalnız aracın KENDİ bacakları arasındaki tutarlılığa,
    SLA ise yalnız GEÇ teslime bakar — erken kalkış hepsinin altından geçiyordu.
    Gerçek veride greedy planın %4,1'i (182 satır) bu ihlali taşıyordu, en uç
    örnekte yük kalkıştan 5 gün 15 saat SONRA doğuyordu.

    Bu, MVP'yi öldüren hata sınıfının (fiziksel olarak geçersiz plan satırı)
    aynısıdır; §6 gereği optimizatörden bağımsız burada, çıktı dosyası üzerinden
    doğrulanır.

    Kontrol yalnız talebin KENDİ çıkış TM'sinden kalkan bacakta yapılır:
    konsolidasyonlu bir yolculukta ara bacakların çıkışı talebin orijinal
    çıkışından farklıdır ve o bacağa yük zaten önceki bacakla gelmiştir
    (`_hesapla_sla`'nın nihai-varış filtresiyle aynı ilke).
    """
    talep_tablosu = kisitlar.talep
    ihlaller = []

    for _, satir in df.iterrows():
        kok_id = str(satir["Talep ID"]).split("-")[0]
        talep_satiri = talep_tablosu[talep_tablosu["talep_id"] == kok_id]
        if talep_satiri.empty:
            continue
        talep_satiri = talep_satiri.iloc[0]

        if satir["Çıkış"] != talep_satiri["cikis"]:
            continue

        saat, dakika = map(int, str(talep_satiri["slot"]).split(":"))
        dogus = pd.Timestamp(talep_satiri["tarih"]).to_pydatetime().replace(
            hour=saat, minute=dakika, second=0, microsecond=0
        )
        kalkis = _tarihe_cevir(satir["Çıkış Tarihi"], satir["Çıkış Saati"])

        if kalkis < dogus:
            ihlaller.append(
                f"  {satir['Araç ID']} / {satir['Talep ID']}: kalkis {kalkis} "
                f"< dogus {dogus} ({satir['Çıkış']} -> {satir['Varış']})"
            )

    if ihlaller:
        gosterilen = "\n".join(ihlaller[:20])
        fazla = f"\n  ... ve {len(ihlaller) - 20} satır daha" if len(ihlaller) > 20 else ""
        raise SimulasyonHatasi(
            f"Yük doğmadan kalkan araç ({len(ihlaller)} satır):\n{gosterilen}{fazla}"
        )


def _tir_dokunuslarini_isle(df: pd.DataFrame, kapasite: KapasiteDefter) -> None:
    """Tır (TM, gün) dokunuşlarını `kapasite`ye işler.

    BACAK bazında (Araç ID + Çıkış + Varış + Çıkış Tarihi/Saati), satır bazında
    DEĞİL: bir bacakta birden fazla Talep ID satırı olabilir (konsolidasyon), ama
    araç o TM'ye yalnız BİR KEZ dokunur. Satır bazında sayarsak aynı dokunuş, o
    bacaktaki talep sayısı kadar çoğaltılmış olur.

    ARA DURAK (zincirleme, §4.1/issue #22): bir aracın rotası birden fazla bacak
    içeriyorsa (ör. A-B-C, iki bacak), önceki bacağın VARIŞ'ı ile sonraki bacağın
    ÇIKIŞ'ı aynı fiziksel durma olayıdır (araç B'de hareket etmeden boşaltılıp
    yeniden yüklenir) — jüri kuralı bunu 2 değil 1 dokunuş sayar (§3: "'Aynı araç
    = 1 slot' kuralı yalnızca araç hareket etmeden boşaltılıp tekrar yüklenirse
    geçerli"). `Servis.duraklar` yapısal olarak tekrarsız olduğu için (bkz.
    katman2_planlama.servis.Servis.__post_init__) bir aracın rotası n bacaksa tam
    olarak n+1 FARKLI durak ziyaret eder — dokunuş sayısı da bu olmalı, bacak uç
    noktalarının (2n) toplamı değil. Bu yüzden aracın İLK bacağının çıkışını bir
    kez, sonra sıradaki HER bacağın varışını bir kez sayıyoruz (n+1 dokunuş).
    Direkt (tek bacaklı) seferlerde bu, önceki (bacak başına 2 dokunuş) davranışla
    birebir aynı sonucu verir — yalnızca çok bacaklı (zincirleme) rotalarda ara
    duraktaki double-count'u düzeltir. Bugüne kadar hiçbir servis üreticisi
    (kiralik_placer/tir_slot_tahsis/servis_havuzu) 2 duraklı olmayan bir Tır
    servisi üretmediği için bu düzeltme mevcut (direkt) senaryoları etkilemez.
    """
    tir_bacaklari = df[df["Araç türü"] == "Tır"].drop_duplicates(
        subset=["Araç ID", "Çıkış", "Varış", "Çıkış Tarihi", "Çıkış Saati",
                "Varış Tarihi", "Varış Saati"]
    )
    for _, grup in tir_bacaklari.groupby("Araç ID"):
        sirali = grup.sort_values(["Çıkış Tarihi", "Çıkış Saati"])
        satirlar = [satir for _, satir in sirali.iterrows()]
        ilk = satirlar[0]
        kapasite.tir_dokunusu_ekle(ilk["Çıkış"], _gun_str(ilk["Çıkış Tarihi"]))
        for satir in satirlar:
            kapasite.tir_dokunusu_ekle(satir["Varış"], _gun_str(satir["Varış Tarihi"]))


def _hesapla_maliyet(df: pd.DataFrame, kisitlar) -> list:
    """Her araç için maliyeti bacak bazında bağımsız hesapla."""
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

        toplam_dk = 0
        toplam_km = 0

        bacaklar = grup.groupby(
            ["Çıkış", "Varış", "Çıkış Tarihi", "Çıkış Saati"]
        )

        for (cikis, varis, _, _), bacak_df in bacaklar:
            # int() DEĞİL: "Taşınan Desi" tam sayı olmak zorunda değil (MILP'in
            # ölçekli çözümü 0,01 desi hassasiyetinde kesirli değerler üretebilir).
            # Kesme (int()), post-pass'in tam hassasiyetle hesapladığı maliyetten
            # küçük ama gerçek bir sapmaya yol açar (kuruş kapısını kırar).
            bacak_desi = float(bacak_df["Taşınan Desi"].sum())
            mesafe = kisitlar.mesafe_km(cikis, varis)
            seyir = kisitlar.seyir_saat(cikis, varis, arac_tipi_ad)

            toplam_dk += kullanim_suresi_dk(bacak_desi, seyir)
            toplam_km += mesafe

        sim_maliyet = arac_maliyeti_tl(saatlik, km_tl, toplam_dk, toplam_km)
        plan_maliyet = grup["Toplam maliyet"].sum()

        if abs(sim_maliyet - plan_maliyet) > 0.01:
            farklar.append({
                "arac_id": arac_id,
                "sim_maliyet": sim_maliyet,
                "plan_maliyet": plan_maliyet,
                "fark": sim_maliyet - plan_maliyet,
            })

    return farklar


def _hesapla_sla(df: pd.DataFrame, kisitlar) -> list:
    """SLA cezasını bağımsız hesapla, planla karşılaştır."""
    farklar = []
    talep_tablosu = kisitlar.talep

    for _, satir in df.iterrows():
        talep_id = satir["Talep ID"]
        desi = float(satir["Taşınan Desi"])

        # Orijinal talep bilgisi
        kok_id = str(talep_id).split("-")[0]
        talep_satiri = talep_tablosu[talep_tablosu["talep_id"] == kok_id]
        if talep_satiri.empty:
            continue
        talep_satiri = talep_satiri.iloc[0]

        # SLA yalnız TALEBİN NİHAİ (orijinal) varış TM'sine ulaşan bacakta
        # değerlendirilir — konsolideli/çok bacaklı bir teslimde ARA duraktaki
        # bacak "Varış"ı orijinal hedeften farklıdır; onu nihai teslim sanıp SLA
        # hesaplarsak (yanlış bir ara-mesafe sla_gun'u ve erken bir ara-varış anıyla)
        # hatalı, çoğunlukla büyük bir ceza uydurulmuş olur. Ara bacaklarda SLA
        # cezası zaten hep 0'dır (§8.2 muhasebe kuralı) — burada da atlanır.
        if satir["Varış"] != talep_satiri["varis"]:
            continue

        # SLA hedef gün — talebin ORİJİNAL çıkış/varışına göre (bacağın kendi
        # çıkış/varışına göre DEĞİL — konsolidasyonda bunlar farklı olabilir).
        sla_gun = kisitlar.sla_gun(talep_satiri["cikis"], talep_satiri["varis"])

        # Deadline: talep tarihi + sla_gun gün, talep saatinde
        talep_tarihi = pd.Timestamp(talep_satiri["tarih"])
        talep_saati = talep_satiri["slot"]
        saat, dakika = map(int, talep_saati.split(":"))

        deadline = talep_tarihi + timedelta(days=sla_gun)
        deadline = deadline.replace(hour=saat, minute=dakika)

        # Gerçek varış zamanı
        varis_dt = _tarihe_cevir(satir["Varış Tarihi"], satir["Varış Saati"])

        if varis_dt > deadline:
            gecikme_dk = int((varis_dt - deadline).total_seconds() / 60)
            sim_ceza = sla_ceza_tl(desi, gecikme_dk)
        else:
            sim_ceza = 0.0

        plan_ceza = float(satir["SLA cezası"])

        if abs(sim_ceza - plan_ceza) > 0.01:
            farklar.append({
                "talep_id": talep_id,
                "sim_ceza": sim_ceza,
                "plan_ceza": plan_ceza,
                "fark": sim_ceza - plan_ceza,
            })

    return farklar


def simulasyonu_calistir(plan_veya_dosya, kisitlar) -> dict:
    """Planı doğrula, maliyeti bağımsız hesapla."""
    if isinstance(plan_veya_dosya, pd.DataFrame):
        df = plan_veya_dosya
    else:
        df = plan_oku(plan_veya_dosya)

    # Yapısal doğrulamalar
    dogrula_arac_tutarliligi(df)
    dogrula_rota_gecerliligi(df)
    dogrula_kiralik(df, kisitlar.kiralik_hatlar)
    dogrula_zaman_cakismasi(df)
    dogrula_dogus_ani(df, kisitlar)

    # Kapasite kontrolü
    kapasite = KapasiteDefter(
        dict(kisitlar.ellecleme_kapasitesi),
        dict(kisitlar.tir_kapasitesi),
    )

    for _, satir in df.iterrows():
        cikis_gun = _gun_str(satir["Çıkış Tarihi"])
        varis_gun = _gun_str(satir["Varış Tarihi"])
        desi = float(satir["Taşınan Desi"])  # int() değil — bkz. _hesapla_maliyet notu
        cikis_tm = satir["Çıkış"]
        varis_tm = satir["Varış"]

        # Çıkış elleçlemesi çıkış gününe
        kapasite.ellecleme_ekle(cikis_tm, cikis_gun, desi)

        # Varış elleçlemesi — gece yarısını aşıyorsa böl
        varis_saati_str = str(satir["Varış Saati"])
        vs, vd = map(int, varis_saati_str.split(":"))
        varis_dakika = vs * 60 + vd
        ell_sure = ellecleme_suresi_dk(desi)

        bugun_oran, yarin_oran = gece_yarisi_bolme(varis_dakika, ell_sure)

        if yarin_oran > 0:
            bugun_desi = desi * bugun_oran
            yarin_desi = desi - bugun_desi
            kapasite.ellecleme_ekle(varis_tm, varis_gun, bugun_desi)
            varis_dt = _tarihe_cevir(satir["Varış Tarihi"], satir["Varış Saati"])
            yarin_str = _gun_str(varis_dt + timedelta(days=1))
            kapasite.ellecleme_ekle(varis_tm, yarin_str, yarin_desi)
        else:
            kapasite.ellecleme_ekle(varis_tm, varis_gun, desi)

    _tir_dokunuslarini_isle(df, kapasite)

    ihlaller = kapasite.dogrula()
    if ihlaller:
        mesaj = "\n".join(ihlaller)
        raise SimulasyonHatasi(f"Kapasite ihlalleri:\n{mesaj}")

    # Maliyet doğrulama
    farklar = _hesapla_maliyet(df, kisitlar)
    if farklar:
        detay = "\n".join(
            f"  {f['arac_id']}: sim={f['sim_maliyet']:.2f} "
            f"plan={f['plan_maliyet']:.2f} fark={f['fark']:.2f}"
            for f in farklar
        )
        raise SimulasyonHatasi(f"Maliyet farkları bulundu:\n{detay}")

    # SLA doğrulama
    sla_farklar = _hesapla_sla(df, kisitlar)
    if sla_farklar:
        detay = "\n".join(
            f"  {f['talep_id']}: sim={f['sim_ceza']:.2f} "
            f"plan={f['plan_ceza']:.2f} fark={f['fark']:.2f}"
            for f in sla_farklar
        )
        raise SimulasyonHatasi(f"SLA ceza farkları bulundu:\n{detay}")

    # Özet
    toplam_arac = df["Araç ID"].nunique()
    toplam_talep = df["Talep ID"].nunique()

    print(f"Simulator: {toplam_arac} arac, {toplam_talep} talep")
    print("Dogrulama: GECTI")

    return {
        "toplam_arac": toplam_arac,
        "toplam_talep": toplam_talep,
        "dogrulama": "GECTI",
    }