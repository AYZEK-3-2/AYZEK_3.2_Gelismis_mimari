# -*- coding: utf-8 -*-
"""katman2_planlama.plan_uret testleri: SLA cezası gerçek gecikmeyi yansıtmalı.

Canlı testte bulunan hata: `_talepleri_ata` ve "atanamamış" (geç-tarihli) yolu
HER satıra sabit `sla_ceza=0.0` yazıyordu — 14 gün geç sevk edilen yükler bile
0 TL ceza gösteriyordu. Bu, muhasebe invariantını (§8.2) yanlış gösterir ve
`katman3_simulator`'ın SLA kapısı `kisitlar.talep`in (tarihsel tablo) tahmin
ID'lerini (D70001+) hiç içermemesi yüzünden bunu hiç yakalamıyordu (bkz.
`katman3_simulator.dogrula_ve_yaz`'ın düzeltmesi).
"""
import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi
from katman2_planlama import _talepleri_ata, plan_uret
from katman3_simulator.simulator import plan_oku, simulasyonu_calistir


class SimpleKisitlar:
    def __init__(self, mesafeler, seyir_saat_deger=2.0, tir_kapasitesi=None,
                 ellecleme_kapasitesi=None, kiralik_hatlar=()):
        cikislar = {c for c, _ in mesafeler}
        varislar = {v for _, v in mesafeler}
        self.transfer_merkezleri = tuple(sorted(cikislar | varislar))
        self.aktif_hatlar = tuple(mesafeler.keys())
        self.arac_tipleri = {
            "Tır": AracTipi("Tır", 20_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyon": AracTipi("Kamyon", 10_000, 150.0, 3.0, 150.0, 3.0),
            "Hafif Kamyon": AracTipi("Hafif Kamyon", 6_000, 100.0, 2.0, 100.0, 2.0),
            "Kamyonet": AracTipi("Kamyonet", 5_000, 80.0, 1.5, 80.0, 1.5),
        }
        self.tir_kapasitesi = tir_kapasitesi or {tm: 5 for tm in self.transfer_merkezleri}
        self.ellecleme_kapasitesi = ellecleme_kapasitesi or {
            tm: 1_000_000.0 for tm in self.transfer_merkezleri
        }
        self.kiralik_hatlar = kiralik_hatlar
        self._mesafe = mesafeler
        self._seyir = seyir_saat_deger

    def hat_var_mi(self, c, v):
        return (c, v) in self._mesafe

    def mesafe_km(self, c, v):
        return self._mesafe[(c, v)]

    def seyir_saat(self, c, v, a):
        return self._seyir

    def sla_gun(self, c, v):
        return 1


def test_plan_uret_dar_kapasitede_sla_cezasi_sifir_degil_ve_kapidan_gecer(tmp_path):
    """A'nın elleçleme kapasitesi kasıtlı olarak çok dar -> yük günlerce
    ötelenmek zorunda kalır. Önceki hata: SLA cezası hep 0.0 yazılıyordu;
    artık gerçek (pozitif) gecikme cezası yazılmalı VE kuruş kapısından
    (kisitlar.talep GERÇEK tahmine ayarlanmış hâliyle) geçmeli."""
    kisitlar = SimpleKisitlar(
        {("A", "B"): 500},
        ellecleme_kapasitesi={"A": 1000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 0, "B": 0},
    )
    tahmin = pd.DataFrame([{
        "talep_id": "D70001", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "tahmin_desi": 5000.0,
    }])

    dosya = plan_uret(kisitlar, tahmin, cikti_dizini=str(tmp_path))
    plan_df = plan_oku(dosya)

    toplam_ceza = plan_df["SLA cezası"].sum()
    assert toplam_ceza > 0.0, "Günlerce ötelenen yükün SLA cezası 0 olamaz"

    kisitlar.talep = pd.DataFrame([{
        "talep_id": "D70001", "cikis": "A", "varis": "B",
        "tarih": pd.Timestamp("2026-06-29"), "slot": "09:00", "toplam_desi": 5000.0,
    }])
    gate = simulasyonu_calistir(plan_df, kisitlar)
    assert gate["dogrulama"] == "GECTI"


def test_plan_uret_zamaninda_teslimde_sla_cezasi_sifir(tmp_path):
    """Bol kapasiteyle aynı gün teslim edilen talepte ceza gerçekten 0 olmalı
    (regresyon: 'her zaman sabit bir sayı yaz' hatasının tersi de test edilmeli)."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    tahmin = pd.DataFrame([{
        "talep_id": "D70002", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "tahmin_desi": 3000.0,
    }])

    dosya = plan_uret(kisitlar, tahmin, cikti_dizini=str(tmp_path))
    plan_df = plan_oku(dosya)

    assert plan_df["SLA cezası"].sum() == pytest.approx(0.0)


def _cok_gunluk_tahmin(gun_sayisi: int, desi: float, ilk_id: int = 70_010):
    """Aynı hatta `gun_sayisi` gün boyunca her iki slotta talep üretir."""
    satirlar = []
    for g in range(gun_sayisi):
        for i, slot in enumerate(("09:00", "17:00")):
            satirlar.append({
                "talep_id": f"D{ilk_id + 2 * g + i:05d}",
                "tarih": pd.Timestamp("2026-06-29") + pd.Timedelta(days=g),
                "cikis": "A", "varis": "B", "slot": slot, "tahmin_desi": desi,
            })
    return pd.DataFrame(satirlar)


def test_plan_uret_hicbir_arac_yuku_dogmadan_kalkmaz(tmp_path):
    """Regresyon (gerçek veride 182 satır / 671.231 desi): `_talepleri_ata`
    kuyruğu (tarih, slot) sırasına, araçları yerleştirme sırasına göre
    eşleştirdiği için bir araç KENDİ kalkışından günler sonra doğacak yükü
    taşıyabiliyordu — fiziksel olarak imkânsız ve hiçbir kapı yakalamıyordu."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    tahmin = _cok_gunluk_tahmin(gun_sayisi=7, desi=4000.0)

    plan_df = plan_oku(plan_uret(kisitlar, tahmin, cikti_dizini=str(tmp_path)))

    dogus = {
        r.talep_id: pd.Timestamp(r.tarih) + pd.Timedelta(hours=int(r.slot[:2]))
        for r in tahmin.itertuples(index=False)
    }
    kalkis = pd.to_datetime(
        plan_df["Çıkış Tarihi"] + " " + plan_df["Çıkış Saati"], format="%d.%m.%Y %H:%M"
    )
    kok = plan_df["Talep ID"].astype(str).str.split("-").str[0].map(dogus)

    erken = plan_df[kalkis < kok]
    assert erken.empty, f"{len(erken)} satırda araç yükü doğmadan kalkmış"


def test_talepleri_ata_bir_arac_birden_fazla_talep_tasir():
    """Regresyon (gerçek veride 608 talep / 1,32M desi sığmıyordu): araç başına
    TEK talep kısıtı, aracın kalan kapasitesini çöpe atıyordu.

    Kapasitesi 10.000 olan TEK araç, 17:00'da kalkıyor; ikisi de o ana kadar
    doğmuş 1.000'er desilik iki talebi birlikte taşımalı ve hiçbiri dışarıda
    kalmamalı. Eski davranışta araç yalnız ilkini alır, ikincisi `atanmamis`
    olarak +14 gün ötelenirdi."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    tahmin = _cok_gunluk_tahmin(gun_sayisi=1, desi=1000.0)   # 09:00 + 17:00
    servis_bilgileri = [{
        "cikis": "A", "varis": "B", "arac_tipi": "Kamyon", "kiralik": False,
        "cikis_ani": pd.Timestamp("2026-06-29 17:30").to_pydatetime(),
        "yuk_desi": 10_000.0,
    }]

    atamalar, atanmamis = _talepleri_ata(servis_bilgileri, tahmin, kisitlar)

    assert atanmamis == []
    (_, talepler), = atamalar
    assert len(talepler) == 2, f"araç yalnız {len(talepler)} talep aldı"
    assert sum(t.desi for t in talepler) == pytest.approx(2000.0)


def test_talepleri_ata_dogmamis_yuku_arac_almaz():
    """Kural 1'in birim testi: 09:00'da kalkan araç, 17:00'da doğacak talebi
    ALAMAZ; o talep atanmamış kalmalı (eski kod hiç kontrol etmiyordu)."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    tahmin = _cok_gunluk_tahmin(gun_sayisi=1, desi=1000.0)
    servis_bilgileri = [{
        "cikis": "A", "varis": "B", "arac_tipi": "Kamyon", "kiralik": False,
        "cikis_ani": pd.Timestamp("2026-06-29 09:30").to_pydatetime(),
        "yuk_desi": 10_000.0,
    }]

    atamalar, atanmamis = _talepleri_ata(servis_bilgileri, tahmin, kisitlar)

    (_, talepler), = atamalar
    assert [t.talep_id for t in talepler] == ["D70010"]      # yalnız 09:00 talebi
    assert [t["talep_id"] for t in atanmamis] == ["D70011"]  # 17:00 talebi bekliyor


def test_plan_uret_coklu_talep_kurus_kapisindan_gecer(tmp_path):
    """Regresyon: birden fazla talep dilimi toplanınca `desi` float gürültüsü
    taşıyor; ham `ceil(desi × 0,01)` katman2 ile katman3'te 1 dakika ayrışıp
    kuruş kapısını araç başına tam bir dakikalık kirayla kırıyordu
    (bkz. config.TAVAN_TOLERANSI_DK). Yük tam kapasiteye oturacak şekilde
    seçildi — gürültünün tavanı devirdiği en kritik nokta orası."""
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    # 5 x 1.000 = 5.000 = Kamyonet kapasitesi (tam dolu)
    satirlar = [{
        "talep_id": f"D{70_100 + i:05d}", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "tahmin_desi": 1000.0,
    } for i in range(5)]
    # aynı (tarih, slot, hat) için tek satır sözleşmesi var; slotları ayır
    for i, s in enumerate(satirlar):
        s["tarih"] = pd.Timestamp("2026-06-29") + pd.Timedelta(days=i)

    tahmin = pd.DataFrame(satirlar)
    plan_df = plan_oku(plan_uret(kisitlar, tahmin, cikti_dizini=str(tmp_path)))

    kisitlar.talep = tahmin.rename(columns={"tahmin_desi": "toplam_desi"})
    assert simulasyonu_calistir(plan_df, kisitlar)["dogrulama"] == "GECTI"
