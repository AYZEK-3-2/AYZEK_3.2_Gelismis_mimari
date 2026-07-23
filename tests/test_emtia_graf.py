# -*- coding: utf-8 -*-
"""Emtia toplulaştırma, zaman-genişletilmiş graf ve akış ayrıştırma testleri
(issue #19, mimari §5.4)."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from katman2_planlama.emtia_graf import (
    AkisTutarsizligi,
    Dugum,
    Kenar,
    akis_ayristir,
    emtia_olustur,
    graf_kur,
)
from katman2_planlama.servis import Servis
from katman2_planlama.servis_havuzu import ServisAdayi


class FakeKisitlarSla:
    """sla_gun için sabit değerler döndüren minimal sahte kısıtlar."""

    def __init__(self, sla_gunleri: dict[tuple, int]):
        self._sla = sla_gunleri

    def sla_gun(self, cikis, varis):
        return self._sla[(cikis, varis)]


class FakeKisitlarSeyir:
    """graf_kur için yalnızca seyir_saat sağlayan minimal sahte kısıtlar."""

    def __init__(self, sure_saat: float = 5.0):
        self._sure = sure_saat

    def seyir_saat(self, cikis, varis, arac_ad):
        return self._sure


# --------------------------------------------------------------------------
# 1) Emtia toplulaştırma + eşleme tablosu
# --------------------------------------------------------------------------

@pytest.fixture
def talep_df_ve_kisitlar():
    kisitlar = FakeKisitlarSla({("A", "C"): 1, ("B", "C"): 1})
    df = pd.DataFrame([
        {"talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"), "cikis": "A",
         "varis": "C", "slot": "09:00", "toplam_desi": 100.0},
        {"talep_id": "D00002", "tarih": pd.Timestamp("2026-06-29"), "cikis": "B",
         "varis": "C", "slot": "09:00", "toplam_desi": 200.0},
        {"talep_id": "D00003", "tarih": pd.Timestamp("2026-06-29"), "cikis": "A",
         "varis": "C", "slot": "17:00", "toplam_desi": 50.0},
    ])
    return df, kisitlar


def test_ayni_varis_ve_sla_bitisi_tek_emtiada_toplaniyor(talep_df_ve_kisitlar):
    df, kisitlar = talep_df_ve_kisitlar
    emtialar, eslesme = emtia_olustur(df, kisitlar)
    # D00001 (A->C, 09:00) ve D00002 (B->C, 09:00) aynı varış + aynı SLA bitişi
    e1 = eslesme.loc[eslesme["talep_id"] == "D00001", "emtia_id"].iloc[0]
    e2 = eslesme.loc[eslesme["talep_id"] == "D00002", "emtia_id"].iloc[0]
    assert e1 == e2


def test_farkli_sla_bitisi_ayri_emtia(talep_df_ve_kisitlar):
    df, kisitlar = talep_df_ve_kisitlar
    emtialar, eslesme = emtia_olustur(df, kisitlar)
    e1 = eslesme.loc[eslesme["talep_id"] == "D00001", "emtia_id"].iloc[0]
    e3 = eslesme.loc[eslesme["talep_id"] == "D00003", "emtia_id"].iloc[0]
    assert e1 != e3
    assert len(emtialar) == 2  # 3 talep -> 2 emtia


def test_eslesme_tablosu_her_talep_tam_bir_kez(talep_df_ve_kisitlar):
    df, kisitlar = talep_df_ve_kisitlar
    _, eslesme = emtia_olustur(df, kisitlar)
    assert sorted(eslesme["talep_id"]) == ["D00001", "D00002", "D00003"]
    for _, row in eslesme.iterrows():
        orijinal = df.loc[df["talep_id"] == row["talep_id"], "toplam_desi"].iloc[0]
        assert row["desi"] == orijinal


def test_sla_bitis_ani_dogru_hesaplaniyor(talep_df_ve_kisitlar):
    df, kisitlar = talep_df_ve_kisitlar
    emtialar, _ = emtia_olustur(df, kisitlar)
    # A->C, sla_gun=1, doğuş 2026-06-29 09:00 -> bitiş 2026-06-30 09:00 (tam 24h)
    hedef = [e for e in emtialar if e.varis == "C" and e.sla_bitis_ani == datetime(2026, 6, 30, 9, 0)]
    assert len(hedef) == 1


def test_gercek_veriyle_toplulastirma_belirgin_azaltiyor():
    from katman0_veri import veriyi_yukle

    kisitlar = veriyi_yukle()
    dilim = kisitlar.talep.head(2000).copy()
    emtialar, eslesme = emtia_olustur(dilim, kisitlar)
    assert len(emtialar) < len(dilim) / 2
    assert len(eslesme) == len(dilim)


# --------------------------------------------------------------------------
# 2) Zaman-genişletilmiş graf
# --------------------------------------------------------------------------

def _aday(duraklar, cikis_ani, arac_tipi="Kamyon", kapasite=10000):
    servis = Servis(arac_tipi=arac_tipi, kiralik=False, duraklar=duraklar, cikis_ani=cikis_ani)
    return ServisAdayi(
        servis=servis, referans_maliyet_tl=100.0, referans_kullanim_dk=300,
        kapasite_desi=kapasite, zorunlu=False,
    )


def test_graf_kur_servis_kenari_sayisi_bacak_sayisina_esit():
    kisitlar = FakeKisitlarSeyir(5.0)
    aday1 = _aday(("A", "B"), datetime(2026, 6, 29, 9, 0))
    aday2 = _aday(("B", "C"), datetime(2026, 6, 29, 15, 0))
    dugumler, kenarlar = graf_kur([aday1, aday2], kisitlar)
    servis_kenarlari = [k for k in kenarlar if k.tur == "servis"]
    assert len(servis_kenarlari) == 2  # her aday 1 bacak


def test_graf_kur_dugum_anlari_ziyaret_ani_ile_birebir():
    kisitlar = FakeKisitlarSeyir(5.0)
    aday1 = _aday(("A", "B"), datetime(2026, 6, 29, 9, 0))
    dugumler, kenarlar = graf_kur([aday1], kisitlar)
    servis_kenari = next(k for k in kenarlar if k.tur == "servis")
    assert servis_kenari.kaynak == Dugum("A", datetime(2026, 6, 29, 9, 0))
    assert servis_kenari.hedef == Dugum("B", datetime(2026, 6, 29, 14, 0))  # 09:00 + 5h


def test_graf_kur_ara_durak_ellecleme_2x():
    # 3 durak A->B->C, kapasite 10.000, her bacak 5h (300 dk). Ara durak (B)
    # konsolidasyon elleçlemesi 2×kapasite = ceil(20000*0.01)=200 dk olmalı
    # (servis_havuzu 3-durak maliyetiyle tutarlı). C varış anı:
    # 09:00 + 300 (A→B) + 200 (B elleçleme) + 300 (B→C) = 09:00 + 800 dk = 22:20.
    # Eski 1× kod 100 dk sayıp 21:40 verirdi.
    kisitlar = FakeKisitlarSeyir(5.0)
    cikis_ani = datetime(2026, 6, 29, 9, 0)
    aday = _aday(("A", "B", "C"), cikis_ani, kapasite=10000)
    _, kenarlar = graf_kur([aday], kisitlar)
    c_kenar = next(k for k in kenarlar if k.tur == "servis" and k.hedef.tm == "C")
    assert c_kenar.hedef.an == cikis_ani + timedelta(minutes=800)


def test_graf_kur_bekleme_kenari_ardisik_anlar_arasinda():
    kisitlar = FakeKisitlarSeyir(5.0)
    # aday1: A->B, varış B 14:00. aday2: B->C, kalkış B 15:00 -> B'de 2 farklı an.
    aday1 = _aday(("A", "B"), datetime(2026, 6, 29, 9, 0))
    aday2 = _aday(("B", "C"), datetime(2026, 6, 29, 15, 0))
    dugumler, kenarlar = graf_kur([aday1, aday2], kisitlar)
    bekleme_kenarlari = [k for k in kenarlar if k.tur == "bekleme"]
    assert len(bekleme_kenarlari) == 1
    bekleme = bekleme_kenarlari[0]
    assert bekleme.kaynak == Dugum("B", datetime(2026, 6, 29, 14, 0))
    assert bekleme.hedef == Dugum("B", datetime(2026, 6, 29, 15, 0))
    assert bekleme.servis_adayi is None


def test_graf_kur_bekleme_kenari_maliyet_tasimaz():
    kisitlar = FakeKisitlarSeyir(5.0)
    aday1 = _aday(("A", "B"), datetime(2026, 6, 29, 9, 0))
    aday2 = _aday(("B", "C"), datetime(2026, 6, 29, 15, 0))
    _, kenarlar = graf_kur([aday1, aday2], kisitlar)
    bekleme = next(k for k in kenarlar if k.tur == "bekleme")
    assert bekleme.servis_adayi is None  # araca maliyet yazacak bir aday yok


# --------------------------------------------------------------------------
# 3) Akış ayrıştırma — elle kurulmuş küçük örnek
# --------------------------------------------------------------------------

def _dugum(tm, an):
    return Dugum(tm, an)


def test_akis_ayristir_bolunmeyen_talep_id_degismez():
    kaynak = _dugum("A", datetime(2026, 6, 29, 9, 0))
    hedef = _dugum("B", datetime(2026, 6, 29, 14, 0))
    kenar = Kenar(kaynak, hedef, "servis", None)
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00001", "cikis": "A",
        "dogus_ani": kaynak.an, "desi": 500.0,
    }])
    sonuc, _ = akis_ayristir("E00001", eslesme, {kenar: 500.0})
    assert len(sonuc) == 1
    assert sonuc[0]["talep_id"] == "D00001"  # bölünmedi, ID aynı kaldı
    assert sonuc[0]["desi"] == 500.0
    assert sonuc[0]["bacaklar"] == [kenar]


def test_akis_ayristir_bolunen_talep_id_suffixli():
    kaynak = _dugum("A", datetime(2026, 6, 29, 9, 0))
    hedef_b = _dugum("B", datetime(2026, 6, 29, 12, 0))
    hedef_d = _dugum("D", datetime(2026, 6, 29, 13, 0))
    kenar_b = Kenar(kaynak, hedef_b, "servis", None)
    kenar_d = Kenar(kaynak, hedef_d, "servis", None)
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00001", "cikis": "A",
        "dogus_ani": kaynak.an, "desi": 500.0,
    }])
    sonuc, _ = akis_ayristir("E00001", eslesme, {kenar_b: 300.0, kenar_d: 200.0})

    # her parça tam bir kez: 2 kaynak dal -> tam 2 sonuç satırı, tekil ID'ler
    assert len(sonuc) == 2
    talep_idler = [p["talep_id"] for p in sonuc]
    assert len(set(talep_idler)) == len(talep_idler)  # tekrar yok

    sonuc_by_id = {p["talep_id"]: p for p in sonuc}
    assert set(sonuc_by_id) == {"D00001-1", "D00001-2"}
    assert sonuc_by_id["D00001-1"]["desi"] == 300.0  # "B" < "D" -> ilk sırada
    assert sonuc_by_id["D00001-2"]["desi"] == 200.0
    # parça toplamı = talep desisi (todo 4)
    assert sum(p["desi"] for p in sonuc) == 500.0


def test_akis_ayristir_kenar_akisi_tam_dusuluyor():
    kaynak = _dugum("A", datetime(2026, 6, 29, 9, 0))
    hedef = _dugum("B", datetime(2026, 6, 29, 14, 0))
    kenar = Kenar(kaynak, hedef, "servis", None)
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00001", "cikis": "A",
        "dogus_ani": kaynak.an, "desi": 500.0,
    }])
    _, kalan = akis_ayristir("E00001", eslesme, {kenar: 500.0})
    assert kalan[kenar] == pytest.approx(0.0)  # fazla/eksik tüketim yok


def test_akis_ayristir_yetersiz_akis_hata_verir():
    kaynak = _dugum("A", datetime(2026, 6, 29, 9, 0))
    hedef = _dugum("B", datetime(2026, 6, 29, 14, 0))
    kenar = Kenar(kaynak, hedef, "servis", None)
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00001", "cikis": "A",
        "dogus_ani": kaynak.an, "desi": 500.0,
    }])
    with pytest.raises(AkisTutarsizligi):
        akis_ayristir("E00001", eslesme, {kenar: 300.0})  # 200 desi karşılıksız


def test_akis_ayristir_farkli_emtia_satiri_hata_verir():
    kaynak = _dugum("A", datetime(2026, 6, 29, 9, 0))
    eslesme = pd.DataFrame([{
        "talep_id": "D00001", "emtia_id": "E00002", "cikis": "A",
        "dogus_ani": kaynak.an, "desi": 100.0,
    }])
    with pytest.raises(AkisTutarsizligi):
        akis_ayristir("E00001", eslesme, {})
