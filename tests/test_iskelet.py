# -*- coding: utf-8 -*-
"""İskelet testleri: klasörler, sabitler ve boş akış yerinde mi."""
import config
import main


def test_sartname_sabitleri():
    assert config.ELLECLEME_DK_PER_DESI == 0.01
    assert config.SLA_CEZA_TL_PER_DESI_SAAT == 0.4
    assert config.TALEP_SAATLERI == ("09:00", "17:00")
    assert config.TALEP_ID_SABLON.format(1) == "D00001"
    assert config.ARAC_ID_SABLON.format(1) == "V0001"


def test_tahmin_ufku():
    fark = config.TAHMIN_BITIS - config.TAHMIN_BASLANGIC
    assert fark.days == 6  # 29.06 09:00 -> 05.07 17:00
    assert config.TAHMIN_SATIR_SAYISI == 289 * 7 * 2


def test_veri_dosyalari_yerinde():
    beklenen = [
        "teknofest26_gelismis.xlsx",
        "sehirler_arasi_lojistik.xlsx",
        "tir_kapasiteleri_v2.xlsx",
        "ellecleme_kapasite.xlsx",
        "kiralik_araclar.xlsx",
        "arac_kapasite_maliyet_saat.xlsx",
    ]
    for ad in beklenen:
        assert (config.VERI_KLASORU / ad).exists(), f"eksik veri dosyası: {ad}"
    assert (config.SABLON_KLASORU / "TASIMA_PLANI_sablon.xlsx").exists()
    assert (config.SABLON_KLASORU / "TALEP_TAHMINI_sablon.xlsx").exists()


def test_bos_akis_calisiyor(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py"])
    main.main()  # uçtan uca akış hatasız dönmeli
