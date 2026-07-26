# -*- coding: utf-8 -*-
"""Katman 3 kalite kapısı testleri: bağımsız maliyet/SLA hesabı planla uyuşmuyorsa
yakalıyor mu (§6). Bu kapı Katman 3'ün varlık sebebi — MVP'nin self-scoring
hatasını önler — o yüzden uyuşmazlığı yakaladığı doğrudan test edilmeli.
"""
from types import SimpleNamespace

import pandas as pd

from katman0_veri.kisitlar import AracTipi
from katman3_simulator.hesaplamalar import (
    arac_maliyeti_tl,
    kullanim_suresi_dk,
)
from katman3_simulator.simulator import _hesapla_maliyet, _hesapla_sla


def _mock_kisitlar():
    tir = AracTipi(
        ad="Tır", kapasite_desi=22400,
        kiralik_saatlik_tl=291.666667, kiralik_km_tl=13,
        spot_saatlik_tl=487.5, spot_km_tl=25,
    )
    talep = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "B", "slot": "09:00", "toplam_desi": 5000,
    }])
    return SimpleNamespace(
        arac_tipleri={"Tır": tir},
        mesafe_km=lambda c, v: 194,
        seyir_saat=lambda c, v, a: 2.98,
        sla_gun=lambda c, v: 1,
        talep=talep,
    )


def _plan(maliyet, sla_ceza=0.0, varis_tarih="30.06.2026", varis_saat="09:00"):
    return pd.DataFrame([{
        "Araç ID": "V0001", "Araç Tipi": "Spot", "Araç türü": "Tır",
        "Çıkış Transfer Merkezi": "A", "Varış Transfer Merkezi": "B",
        "Çıkış Tarihi": "29.06.2026", "Çıkış Saati": "09:00",
        "Varış Tarihi": varis_tarih, "Varış Saati": varis_saat,
        "Talep ID": "D00001", "Taşınan Desi": 5000,
        "Yolculuk süresi": 179, "Çıkış Elleçleme süresi": 50,
        "Varış elleçleme süresi": 50,
        "Toplam maliyet": maliyet, "SLA cezası": sla_ceza,
    }])


def _dogru_maliyet():
    return arac_maliyeti_tl(487.5, 25, kullanim_suresi_dk(5000, 2.98), 194)


# --- maliyet kapısı ----------------------------------------------------------

def test_maliyet_dogruysa_fark_yok():
    k = _mock_kisitlar()
    assert _hesapla_maliyet(_plan(_dogru_maliyet()), k) == []


def test_maliyet_yanlissa_yakalanir():
    k = _mock_kisitlar()
    farklar = _hesapla_maliyet(_plan(_dogru_maliyet() + 1000), k)  # kasıtlı yanlış
    assert len(farklar) == 1
    assert farklar[0]["arac_id"] == "V0001"


# --- SLA kapısı --------------------------------------------------------------

def test_sla_zamaninda_ceza_yok():
    k = _mock_kisitlar()
    # deadline = 29.06 09:00 + 1 gün = 30.06 09:00; varış tam 30.06 09:00
    assert _hesapla_sla(_plan(0.0, varis_saat="09:00"), k) == []


def test_sla_gecikme_yakalanir():
    k = _mock_kisitlar()
    # varış 30.06 12:00 → 3 saat gecikme; plan cezayı 0 yazmış → kapı yakalamalı
    farklar = _hesapla_sla(_plan(0.0, varis_saat="12:00"), k)
    assert len(farklar) == 1
    # 5000 desi × ceil(180dk) 3 saat × 0.4 = 6000 TL beklenen
    assert farklar[0]["sim_ceza"] == 6000.0


# --- kesirli desi (int() kesme regresyonu, issue #21 geliştirmesinde bulundu) --------

def test_maliyet_kesirli_desi_int_kesmesi_olmadan_dogru():
    """'Taşınan Desi' tam sayı olmak zorunda değil (MILP'in ölçekli çözümü 0,01
    hassasiyetinde kesirli değerler üretebilir). Önceden `int(...)` ile kesiliyordu
    ve gerçek maliyetten sapan yanlış bir 'fark' üretiyordu — bu artık olmamalı.
    """
    k = _mock_kisitlar()
    kesirli_desi = 4999.92
    dogru_maliyet = arac_maliyeti_tl(487.5, 25, kullanim_suresi_dk(kesirli_desi, 2.98), 194)
    plan = _plan(dogru_maliyet)
    plan["Taşınan Desi"] = plan["Taşınan Desi"].astype(float)
    plan.loc[0, "Taşınan Desi"] = kesirli_desi

    assert _hesapla_maliyet(plan, k) == []


# --- ara bacakta SLA hesaplanmaması (issue #21 geliştirmesinde bulundu) --------------

def test_sla_sadece_nihai_varista_hesaplanir_ara_bacakta_degil():
    """Konsolideli (çok bacaklı) bir teslimde ARA duraktaki bacağın 'Varış'ı
    orijinal hedeften farklıdır. Eskiden her satır nihai teslim sanılıp o bacağın
    KENDİ (kısa) rotasının sla_gun'uyla ceza hesaplanıyordu — ara bacak erken/geç
    olsa da alakasız, uydurma büyük cezalar üretiyordu. Şimdi yalnız orijinal
    varış TM'sine ulaşan satırda SLA değerlendirilmeli.
    """
    tir = AracTipi(
        ad="Tır", kapasite_desi=22400,
        kiralik_saatlik_tl=291.666667, kiralik_km_tl=13,
        spot_saatlik_tl=487.5, spot_km_tl=25,
    )
    talep = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp("2026-06-29"),
        "cikis": "A", "varis": "C", "slot": "09:00", "toplam_desi": 5000,
    }])
    # A->B sla_gun=1 (kısa, ara bacağın KENDİ rotası) ama A->C (gerçek rota) sla_gun=3
    sla_gunleri = {("A", "B"): 1, ("B", "C"): 1, ("A", "C"): 3}
    kisitlar = SimpleNamespace(
        arac_tipleri={"Tır": tir},
        mesafe_km=lambda c, v: 194,
        seyir_saat=lambda c, v, a: 2.98,
        sla_gun=lambda c, v: sla_gunleri[(c, v)],
        talep=talep,
    )
    df = pd.DataFrame([
        {
            "Araç ID": "V0001", "Araç Tipi": "Spot", "Araç türü": "Tır",
            "Çıkış Transfer Merkezi": "A", "Varış Transfer Merkezi": "B",
            "Çıkış Tarihi": "29.06.2026", "Çıkış Saati": "09:00",
            "Varış Tarihi": "29.06.2026", "Varış Saati": "12:00",
            "Talep ID": "D00001", "Taşınan Desi": 5000,
            "Yolculuk süresi": 179, "Çıkış Elleçleme süresi": 50,
            "Varış elleçleme süresi": 50, "Toplam maliyet": 1000.0, "SLA cezası": 0.0,
        },
        {
            "Araç ID": "V0001", "Araç Tipi": "Spot", "Araç türü": "Tır",
            "Çıkış Transfer Merkezi": "B", "Varış Transfer Merkezi": "C",
            "Çıkış Tarihi": "29.06.2026", "Çıkış Saati": "12:50",
            "Varış Tarihi": "30.06.2026", "Varış Saati": "09:00",
            "Talep ID": "D00001", "Taşınan Desi": 5000,
            "Yolculuk süresi": 179, "Çıkış Elleçleme süresi": 50,
            "Varış elleçleme süresi": 50, "Toplam maliyet": 0.0, "SLA cezası": 0.0,
        },
    ])

    assert _hesapla_sla(df, kisitlar) == []
