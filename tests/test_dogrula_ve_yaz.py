# -*- coding: utf-8 -*-
"""`katman3_simulator.dogrula_ve_yaz` testleri.

Canlı testte bulunan hata: `simulasyonu_calistir(plan_df, veri)` çağrısı
`veri.talep`i (katman0'ın yüklediği TARİHSEL 66k satırlık tabloyu) kullanıyordu.
`talep_id_ata`'nın tahmin ID'leri kasıtlı olarak bu tarihsel aralığın dışında
(D70001+, "güvenli boşluk") başladığı için SLA kontrolü bu ID'leri hiç bulamıyor
ve SESSİZCE atlıyordu — planın SLA cezası sütunu yanlış olsa bile kapı bunu
hiç yakalamıyordu. `dogrula_ve_yaz` artık `tahmin`den (gerçek talep) türetilmiş
bir tabloyla doğruluyor.
"""
from datetime import datetime

import pandas as pd
import pytest

from katman0_veri.kisitlar import AracTipi, Kisitlar
from katman3_simulator import dogrula_ve_yaz
from katman3_simulator.simulator import SimulasyonHatasi


def _kisitlar() -> Kisitlar:
    tir = AracTipi("Tır", 20_000, 100.0, 2.0, 100.0, 2.0)
    # kisitlar.talep (tarihsel) BİLEREK tahmin ID aralığıyla (D70001+) hiç
    # örtüşmeyen, eski (D00001 aralığı) bir talep içeriyor -- gerçek main.py
    # akışıyla birebir aynı senaryo.
    tarihsel_talep = pd.DataFrame([{
        "talep_id": "D00001", "tarih": pd.Timestamp("2026-01-01"),
        "cikis": "A", "varis": "B", "slot": "09:00", "toplam_desi": 100.0,
    }])
    return Kisitlar(
        transfer_merkezleri=("A", "B"),
        aktif_hatlar=(("A", "B"),),
        arac_tipleri={"Tır": tir},
        tir_kapasitesi={"A": 5, "B": 5},
        ellecleme_kapasitesi={"A": 1_000_000.0, "B": 1_000_000.0},
        kiralik_hatlar=(),
        _mesafe_km={("A", "B"): 100},
        _sla_gun={("A", "B"): 1},
        _seyir_saat={("A", "B", "Tır"): 2.0},
        talep=tarihsel_talep,
    )


def _tahmin_df():
    return pd.DataFrame([{
        "Talep ID": "D70001", "Tarih": "29.06.2026",
        "Talep Tamamlama Saati": "09:00:00",
        "Çıkış Transfer Merkezi": "A", "Varış Transfer Merkezi": "B",
        "Tahmin Edilen Desi": 5000.0,
    }])


def _plan_df(sla_ceza):
    return pd.DataFrame([{
        "Araç ID": "V0001", "Araç Tipi": "Spot", "Araç türü": "Tır",
        "Çıkış": "A", "Varış": "B",
        "Çıkış Tarihi": "29.06.2026", "Çıkış Saati": "09:00",
        "Varış Tarihi": "29.06.2026", "Varış Saati": "12:00",
        "Talep ID": "D70001", "Taşınan Desi": 5000.0,
        "Yolculuk süresi": 120, "Çıkış elleçleme süresi": 50,
        "Varış elleçleme süresi": 50,
        "Toplam maliyet": 100.0 * (50 + 120 + 50) / 60 + 2.0 * 100,
        "SLA cezası": sla_ceza,
    }])


def test_dogru_sla_cezasiyla_kapidan_gecer(tmp_path):
    veri = _kisitlar()
    tahmin = _tahmin_df()
    plan_df = _plan_df(sla_ceza=0.0)  # zamanında teslim, ceza gerçekten 0
    plan_yolu = tmp_path / "Tasima-plani.xlsx"
    plan_df.to_excel(plan_yolu, index=False)

    sonuc = dogrula_ve_yaz(veri, tahmin, str(plan_yolu))

    assert sonuc["dogrulama"] == "GECTI"


def test_yanlis_sla_cezasi_artik_yakalaniyor(tmp_path):
    """ÖNCEDEN: veri.talep (tarihsel) kullanıldığı için D70001 hiç bulunamaz,
    SLA kontrolü atlanır, bu YANLIŞ (0.0) ceza sessizce geçerdi. ARTIK:
    tahmin'e göre doğrulama yapıldığı için yakalanmalı."""
    veri = _kisitlar()
    tahmin = _tahmin_df()
    # Varış 12:00, SLA bitişi 30.06 09:00 (1 gün) -- çok erken, ceza olmamalı;
    # ama plan KASITLI OLARAK yanlış (sahte) bir ceza beyan ediyor.
    plan_df = _plan_df(sla_ceza=99999.0)
    plan_yolu = tmp_path / "Tasima-plani.xlsx"
    plan_df.to_excel(plan_yolu, index=False)

    with pytest.raises(SimulasyonHatasi, match="SLA ceza farkları"):
        dogrula_ve_yaz(veri, tahmin, str(plan_yolu))
