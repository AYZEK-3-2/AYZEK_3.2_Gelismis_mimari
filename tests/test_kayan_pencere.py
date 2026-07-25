# -*- coding: utf-8 -*-
"""Kayan pencere sürücüsü testleri (issue #21, mimari §5.4).

Bağımlılıklar (CP-SAT modeli #20, greedy atama #12-16) mergeli. Kabul kriterleri:
1. MILP sonucu her koşuda greedy'den kötü değil.
2. Post-pass sonrası plan simülatörün kuruş kapısından geçiyor.
3. MILP greedy'yi yenemiyorsa neden `pencere_raporu`ya not düşülüyor.
"""
from datetime import datetime

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi
from katman2_planlama.kayan_pencere import _greedy_ipucu_uret, kayan_pencere_coz
from katman2_planlama.plan_yazici import plan_yaz
from katman2_planlama.servis import Servis
from katman2_planlama.servis_havuzu import ServisAdayi
from katman3_simulator.simulator import simulasyonu_calistir

TAHMIN_BASLANGIC = datetime(2026, 6, 29, 9, 0)


class SimpleKisitlar:
    """Test için minimal Kisitlar arayüzü (tüm greedy+MILP zincirinin ihtiyaç
    duyduğu alanları taşır)."""

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


def _talep_df(gun_sayisi, cikis="A", varis="B", desi=1500.0):
    satirlar = []
    tid = 1
    for gun in range(gun_sayisi):
        tarih = pd.Timestamp(TAHMIN_BASLANGIC.date()) + pd.Timedelta(days=gun)
        for slot in ("09:00", "17:00"):
            satirlar.append({
                "talep_id": f"D{tid:05d}", "tarih": tarih, "cikis": cikis, "varis": varis,
                "slot": slot, "toplam_desi": desi,
            })
            tid += 1
    return pd.DataFrame(satirlar)


def _kok(talep_id: str) -> str:
    return talep_id.split("-")[0]


def _talep_toplamlari(arac_planlari):
    toplam: dict[str, float] = {}
    for arac in arac_planlari:
        for bacak in arac.bacaklar:
            for talep in bacak.talepler:
                if talep.son_bacak:
                    toplam[_kok(talep.talep_id)] = toplam.get(_kok(talep.talep_id), 0.0) + talep.desi
    return toplam


# --------------------------------------------------------------------------
# Greedy -> hint adaptörü
# --------------------------------------------------------------------------

def test_greedy_ipucu_degerce_eslesen_adaylari_sayar():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    t = datetime(2026, 6, 29, 10, 0)
    ortak_servis = Servis("Kamyon", False, ("A", "B"), t)
    aday = ServisAdayi(ortak_servis, 0.0, 0, 10_000, False)
    baska_aday = ServisAdayi(Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 15, 0)), 0.0, 0, 10_000, False)

    ipucu = _greedy_ipucu_uret([ortak_servis, ortak_servis], (aday, baska_aday))

    assert ipucu == {aday: 2}


def test_greedy_ipucu_farkli_dakikada_da_en_yakin_gec_esit_adaya_eslenir():
    """Greedy kalkışı gerçek yükle, havuz adayınınki tam kapasite varsayımıyla
    hesaplandığı için dakikası neredeyse hiç örtüşmez (§5.4) — tam değer değil,
    aynı rotada kendi kalkışından GERİDE OLMAYAN en yakın adaya eşlenmeli.
    """
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    erken_aday = ServisAdayi(Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 9, 50)), 0.0, 0, 10_000, False)
    gec_aday = ServisAdayi(Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 17, 50)), 0.0, 0, 10_000, False)
    greedy_servis = Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 9, 30))  # gerçek yükle erken kalkış

    ipucu = _greedy_ipucu_uret([greedy_servis], (erken_aday, gec_aday))

    assert ipucu == {erken_aday: 1}


def test_greedy_ipucu_rota_havuzda_hic_yoksa_atlanir():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    aday = ServisAdayi(Servis("Kamyon", False, ("A", "B"), datetime(2026, 6, 29, 10, 0)), 0.0, 0, 10_000, False)
    baska_rota = Servis("Kamyon", False, ("A", "C"), datetime(2026, 6, 29, 10, 0))  # havuzda hiç yok

    ipucu = _greedy_ipucu_uret([baska_rota], (aday,))

    assert ipucu == {}


# --------------------------------------------------------------------------
# 3 günlük pencere sürücüsü: pencere sınırını aşan servis + bekleyen yükün devri
# --------------------------------------------------------------------------

def test_pencere_disindaki_adaylar_havuza_girmiyor():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    from katman2_planlama.servis_havuzu import havuz_uret
    havuz = havuz_uret(kisitlar, talep_df, TAHMIN_BASLANGIC)
    pencere0_baslangic = TAHMIN_BASLANGIC.date()
    pencere0_bitis = pencere0_baslangic + pd.Timedelta(days=3)

    disaridakiler = [
        a for a in havuz.adaylar
        if not (pencere0_baslangic <= a.servis.cikis_ani.date() < pencere0_bitis)
    ]
    # Havuzda 7 günlük aday var (talep 7 gün); pencere 0 yalnız ilk 3 günü kapsar ->
    # en az bir kısmı (4.-7. günler) pencere dışında kalmalı.
    assert len(disaridakiler) > 0
    assert len(disaridakiler) < len(havuz.adaylar)


def test_bekleyen_yuk_kapasite_asiminda_sonraki_pencereye_devrediyor():
    """A'nın günlük elleçleme kapasitesi 4000; TEK bir 10.000 desilik dev talep var.
    Gün-0 tek başına asla karşılayamaz (10.000 > 4000) -> birden fazla pencereye
    devretmek ZORUNDA. Tır'ı devre dışı bırakıyoruz çünkü mevcut tir_slot_tahsis
    (issue #14, dokunulmuyor) elleçleme kapasitesini kontrol etmiyor — bu test
    yalnız kayan pencerenin devir mekanizmasını izole etmek istiyor.
    """
    kisitlar = SimpleKisitlar(
        {("A", "B"): 100},
        ellecleme_kapasitesi={"A": 4000.0, "B": 1_000_000.0},
        tir_kapasitesi={"A": 0, "B": 0},
    )
    talep_df = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp(TAHMIN_BASLANGIC.date()),
        "cikis": "A", "varis": "B", "slot": "09:00", "toplam_desi": 10_000.0,
    }])

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    # Birden fazla pencere gerekmiş olmalı (tek pencerede/günde sığmaz)
    assert len(sonuc.pencere_raporu) > 1
    # Ama sonunda TAMAMI teslim edilmiş olmalı — hiçbir desi kaybolmamış
    teslim = sum(
        t.desi for arac in sonuc.arac_planlari for b in arac.bacaklar
        for t in b.talepler if t.son_bacak
    )
    assert teslim == pytest.approx(10_000.0, abs=0.5)

    # kuruş kapısından da geçmeli
    kisitlar.talep = talep_df
    plan_df = plan_yaz(sonuc.arac_planlari)
    gate = simulasyonu_calistir(plan_df, kisitlar)
    assert gate["dogrulama"] == "GECTI"


def test_cok_hatli_kiralikli_senaryo_ucdan_uca():
    """3 TM (A,B,C), 3 hat, A->B'de zorunlu kiralık — gerçek kullanım şekline en
    yakın bütünleşik test. Bu senaryo geliştirme sürecinde canlı test edilerek
    peş peşe bulunan birkaç hatayı ortaya çıkardı: kiralık-dışı hatların
    kalan_talep_df'e eklenmemesi, aynı bacakta çoklu talebin simülatörde yanlış
    zaman çakışması/tır dokunuşu sayılması, akış ayrıştırıcısını bozan "kısmi
    teslim + kısmi bekleyerek devam" belirsizliği, CP-SAT'ın determinizm eksikliği
    ve devreden yükün bin-pack'te yanlış (eski) güne atanması. Hepsi düzeltildi;
    bu test o düzeltmelerin kalıcı kanıtı.
    """
    from katman0_veri.kisitlar import KiralikHat

    kisitlar = SimpleKisitlar(
        {("A", "B"): 100, ("A", "C"): 150, ("B", "C"): 120},
        kiralik_hatlar=(KiralikHat("A", "B", "Kamyon", 2),),
    )
    satirlar = []
    tid = 1
    for gun in range(7):
        tarih = pd.Timestamp(TAHMIN_BASLANGIC.date()) + pd.Timedelta(days=gun)
        for cikis, varis in kisitlar.aktif_hatlar:
            for slot in ("09:00", "17:00"):
                satirlar.append({
                    "talep_id": f"D{tid:05d}", "tarih": tarih, "cikis": cikis, "varis": varis,
                    "slot": slot, "toplam_desi": 3000.0,
                })
                tid += 1
    talep_df = pd.DataFrame(satirlar)
    kisitlar.talep = talep_df

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    # Hiçbir desi kaybolmamış
    toplamlar = _talep_toplamlari(sonuc.arac_planlari)
    for row in talep_df.itertuples(index=False):
        assert toplamlar.get(row.talep_id, 0.0) == pytest.approx(row.toplam_desi, abs=0.5), (
            f"{row.talep_id} eksik/hatalı karşılandı"
        )

    # Hiçbir pencerede greedy'den kötü değil
    for row in sonuc.pencere_raporu.itertuples(index=False):
        secilen_maliyet = row.milp_maliyet_tl if row.secilen == "milp" else row.greedy_maliyet_tl
        assert secilen_maliyet <= row.greedy_maliyet_tl + 0.01
        # "bedava boş plan" regresyonu: seçilen taraf asla sıfır maliyetle "kazanmamalı"
        # (o pencerede gerçekten committed bir şey olduğu sürece)
        if secilen_maliyet == 0.0:
            assert row.greedy_maliyet_tl == 0.0  # yalnız GERÇEKTEN iki taraf da boşsa 0 kabul

    # kuruş kapısından geçiyor
    plan_df = plan_yaz(sonuc.arac_planlari)
    gate = simulasyonu_calistir(plan_df, kisitlar)
    assert gate["dogrulama"] == "GECTI"


def test_milp_coz_determinist():
    """Aynı girdiyle art arda iki koşu birebir aynı araç sayısı/maliyeti vermeli
    (proje kuralı: teslim edilen dosyalar her koşuda bit düzeyinde aynı olmalı,
    config.SEED). CP-SAT'a sabit seed verilmezse `set` iterasyon sırası
    (PYTHONHASHSEED) yüzünden koşudan koşuya farklı (eşit-optimal) çözümler
    bulunabiliyordu — bu test o düzeltmenin kalıcı kanıtı.
    """
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    sonuc1 = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)
    sonuc2 = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    assert len(sonuc1.arac_planlari) == len(sonuc2.arac_planlari)
    maliyet1 = sum(a.toplam_maliyet for a in sonuc1.arac_planlari)
    maliyet2 = sum(a.toplam_maliyet for a in sonuc2.arac_planlari)
    assert maliyet1 == pytest.approx(maliyet2, abs=0.01)


# --------------------------------------------------------------------------
# Kabul kriteri 1: MILP sonucu her pencerede greedy'den kötü değil
# --------------------------------------------------------------------------

def test_milp_hicbir_pencerede_greedyden_kotu_degil():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    assert len(sonuc.pencere_raporu) > 0
    for row in sonuc.pencere_raporu.itertuples(index=False):
        secilen_maliyet = row.milp_maliyet_tl if row.secilen == "milp" else row.greedy_maliyet_tl
        assert secilen_maliyet <= row.greedy_maliyet_tl + 0.01, (
            f"pencere {row.pencere_no}: seçilen ({row.secilen}, {secilen_maliyet}) "
            f"greedy'den ({row.greedy_maliyet_tl}) pahalı!"
        )


def test_talep_butunlugu_hicbir_desi_kaybolmuyor():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    toplamlar = _talep_toplamlari(sonuc.arac_planlari)
    for row in talep_df.itertuples(index=False):
        assert toplamlar.get(row.talep_id, 0.0) == pytest.approx(row.toplam_desi, abs=0.5)


def test_pencere_raporu_sutunlari_ve_pencere_bazinda_kiyas():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    beklenen_sutunlar = {
        "pencere_no", "ilk_gun", "son_gun", "greedy_maliyet_tl", "milp_maliyet_tl",
        "secilen", "milp_durum", "milp_gap", "sure_sn", "not_",
    }
    assert beklenen_sutunlar.issubset(set(sonuc.pencere_raporu.columns))
    assert sonuc.pencere_raporu["pencere_no"].is_unique


def test_toplam_sure_logu_kaydediliyor():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)

    assert sonuc.toplam_sure_sn > 0.0
    assert sonuc.pencere_raporu["sure_sn"].sum() <= sonuc.toplam_sure_sn + 0.01


# --------------------------------------------------------------------------
# Kabul kriteri 2: post-pass sonrası plan simülatörün kuruş kapısından geçiyor
# --------------------------------------------------------------------------

def test_kurus_kapisindan_geciyor():
    kisitlar = SimpleKisitlar({("A", "B"): 100})
    talep_df = _talep_df(gun_sayisi=7)
    kisitlar.talep = talep_df

    sonuc = kayan_pencere_coz(kisitlar, talep_df, TAHMIN_BASLANGIC, pencere_zaman_limit_sn=15.0)
    plan_df = plan_yaz(sonuc.arac_planlari)

    gate_sonuc = simulasyonu_calistir(plan_df, kisitlar)
    assert gate_sonuc["dogrulama"] == "GECTI"
