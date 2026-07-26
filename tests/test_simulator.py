import pandas as pd
import pytest
from katman3_simulator.kapasite import KapasiteDefter
from katman3_simulator.simulator import (
    dogrula_arac_tutarliligi,
    dogrula_rota_gecerliligi,
    dogrula_zaman_cakismasi,
    _tir_dokunuslarini_isle,
    SimulasyonHatasi,
)


def sahte_plan(**degisiklikler):
    """Test için sahte plan DataFrame'i oluşturur."""
    veri = {
        "Araç ID": ["V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot"],
        "Araç türü": ["Tır", "Tır"],
        "Çıkış": ["İstanbul", "İstanbul"],
        "Varış": ["Yalova", "Yalova"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "09:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:30", "10:30"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        "Çıkış elleçleme süresi": [80, 80],
        "Varış elleçleme süresi": [80, 80],
        "Toplam maliyet": [5000.0, 0.0],
        "SLA cezası": [0.0, 0.0],
    }
    veri.update(degisiklikler)
    return pd.DataFrame(veri)


# --- Araç tutarlılığı ---

def test_ayni_arac_tek_tur():
    """Aynı araç tek tür olmalı — sorunsuz geçmeli."""
    df = sahte_plan()
    dogrula_arac_tutarliligi(df)


def test_arac_tur_degistirirse_hata():
    """Aynı araç hem Tır hem Kamyon olamaz."""
    df = sahte_plan(**{"Araç türü": ["Tır", "Kamyon"]})
    with pytest.raises(SimulasyonHatasi, match="birden fazla araç türü"):
        dogrula_arac_tutarliligi(df)


# --- Rota geçerliliği ---

def test_gecerli_rota():
    """Çıkış varıştan önce — sorunsuz geçmeli."""
    df = sahte_plan()
    dogrula_rota_gecerliligi(df)


def test_hayalet_rota_reddedilir():
    """MVP hatası: araç [O, O2, D] rotasına O2->D2 talebi bağlanamaz.

    Araç İstanbul -> Yalova -> Eskişehir gidiyor.
    D00002 talebi Eskişehir -> Yalova diyor ama araç tersten gidiyor.
    Bu reddedilmeli.
    """
    df = pd.DataFrame({
        "Araç ID": ["V0001", "V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot", "Spot"],
        "Araç türü": ["Tır", "Tır", "Tır"],
        "Çıkış": ["İstanbul", "Eskişehir", "Yalova"],
        "Varış": ["Yalova", "Yalova", "Eskişehir"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "09:00", "11:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:00", "10:00", "12:00"],
        "Talep ID": ["D00001", "D00002", "D00003"],
        "Taşınan Desi": [5000, 3000, 2000],
        "Yolculuk süresi": [56, 56, 56],
        "Çıkış elleçleme süresi": [80, 80, 80],
        "Varış elleçleme süresi": [80, 80, 80],
        "Toplam maliyet": [5000.0, 0.0, 0.0],
        "SLA cezası": [0.0, 0.0, 0.0],
    })
    # Rota sıralama sonrası: İstanbul, Yalova, Eskişehir
    # D00002 Eskişehir->Yalova diyor ama Eskişehir sonra geliyor = hata
    with pytest.raises(SimulasyonHatasi, match="sırası yanlış"):
        dogrula_rota_gecerliligi(df)


def test_ters_rota_reddedilir():
    """Araç A->B gidiyor ama talep B->A diyor — reddedilmeli."""
    df = pd.DataFrame({
        "Araç ID": ["V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot"],
        "Araç türü": ["Tır", "Tır"],
        "Çıkış": ["İstanbul", "Yalova"],
        "Varış": ["Yalova", "İstanbul"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "11:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:00", "12:00"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        "Çıkış elleçleme süresi": [80, 80],
        "Varış elleçleme süresi": [80, 80],
        "Toplam maliyet": [5000.0, 0.0],
        "SLA cezası": [0.0, 0.0],
    })
    # Rota: İstanbul -> Yalova -> İstanbul (gidiş-dönüş)
    # D00002: Yalova -> İstanbul, Yalova idx=1, İstanbul idx=0 → hata
    with pytest.raises(SimulasyonHatasi, match="sırası yanlış"):
        dogrula_rota_gecerliligi(df)


# --- Zaman çakışması ---

def test_zaman_cakismasi_yok():
    """Seferler sıralı — çakışma yok."""
    df = pd.DataFrame({
        "Araç ID": ["V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot"],
        "Araç türü": ["Tır", "Tır"],
        "Çıkış": ["İstanbul", "Yalova"],
        "Varış": ["Yalova", "Eskişehir"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "11:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:00", "13:00"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        "Çıkış elleçleme süresi": [80, 80],
        "Varış elleçleme süresi": [80, 80],
        "Toplam maliyet": [5000.0, 0.0],
        "SLA cezası": [0.0, 0.0],
    })
    dogrula_zaman_cakismasi(df)


def test_zaman_cakismasi_hata():
    """Araç 10:30'da varıyor ama 10:00'da yeni sefere çıkıyor — imkansız."""
    df = pd.DataFrame({
        "Araç ID": ["V0001", "V0001"],
        "Araç Tipi": ["Spot", "Spot"],
        "Araç türü": ["Tır", "Tır"],
        "Çıkış": ["İstanbul", "Yalova"],
        "Varış": ["Yalova", "Eskişehir"],
        "Çıkış Tarihi": ["29.06.2026", "29.06.2026"],
        "Çıkış Saati": ["09:00", "10:00"],
        "Varış Tarihi": ["29.06.2026", "29.06.2026"],
        "Varış Saati": ["10:30", "13:00"],
        "Talep ID": ["D00001", "D00002"],
        "Taşınan Desi": [5000, 3000],
        "Yolculuk süresi": [56, 56],
        "Çıkış elleçleme süresi": [80, 80],
        "Varış elleçleme süresi": [80, 80],
        "Toplam maliyet": [5000.0, 0.0],
        "SLA cezası": [0.0, 0.0],
    })
    with pytest.raises(SimulasyonHatasi, match="zaman çakışması"):
        dogrula_zaman_cakismasi(df)


# --- Tır dokunuş sayımı (§4.1/§3, issue #22 LNS zincirleme öncesi düzeltme) ---

def _tir_bacak(arac_id, cikis, varis, cikis_tarih, cikis_saat, varis_tarih, varis_saat):
    return {
        "Araç ID": arac_id, "Araç türü": "Tır",
        "Çıkış": cikis, "Varış": varis,
        "Çıkış Tarihi": cikis_tarih, "Çıkış Saati": cikis_saat,
        "Varış Tarihi": varis_tarih, "Varış Saati": varis_saat,
    }


def test_direkt_tir_iki_ucta_birer_dokunus_sayar():
    """Regresyon: tek bacaklı (direkt) sefer önceki davranışla birebir aynı —
    çıkışta 1, varışta 1, toplam 2 dokunuş."""
    df = pd.DataFrame([
        _tir_bacak("V0001", "İstanbul", "Yalova", "29.06.2026", "09:00", "29.06.2026", "10:00"),
    ])
    kapasite = KapasiteDefter({}, {"İstanbul": 5, "Yalova": 5})
    _tir_dokunuslarini_isle(df, kapasite)

    assert kapasite.tir_kullanim[("İstanbul", "29.06.2026")] == 1
    assert kapasite.tir_kullanim[("Yalova", "29.06.2026")] == 1
    assert sum(kapasite.tir_kullanim.values()) == 2


def test_zincirleme_ara_durakta_tek_dokunus_sayar():
    """Aynı araç (V0001) A-B-C zincirlemesi yapıyor: B'de hareket etmeden
    boşaltıp yeniden yüklüyor (§3, §4.1) → B'de 1 dokunuş, 2 DEĞİL.
    Toplam 3 dokunuş (A, B, C) — len(duraklar) ile birebir, bacak uç noktalarının
    toplamı (4) değil.
    """
    df = pd.DataFrame([
        _tir_bacak("V0001", "İstanbul", "Yalova", "29.06.2026", "09:00", "29.06.2026", "10:00"),
        _tir_bacak("V0001", "Yalova", "Eskişehir", "29.06.2026", "10:00", "29.06.2026", "13:00"),
    ])
    kapasite = KapasiteDefter({}, {"İstanbul": 5, "Yalova": 1, "Eskişehir": 5})
    _tir_dokunuslarini_isle(df, kapasite)

    assert kapasite.tir_kullanim[("İstanbul", "29.06.2026")] == 1
    assert kapasite.tir_kullanim[("Yalova", "29.06.2026")] == 1  # 2 değil!
    assert kapasite.tir_kullanim[("Eskişehir", "29.06.2026")] == 1
    assert sum(kapasite.tir_kullanim.values()) == 3

    # Yalova'nın kapasitesi tam 1 — zincirleme olmasaydı (2 dokunuş) aşım olurdu.
    assert kapasite.dogrula() == []


def test_iki_bagimsiz_direkt_sefer_ara_tmde_iki_dokunus_sayar():
    """Karşıt senaryo (mimari §4.1): A->B ve B->C AYRI araçlarla (V0001, V0002)
    yapılırsa B'de 2 dokunuş yer — zincirlemenin tam ürettiği tasarruf budur.
    """
    df = pd.DataFrame([
        _tir_bacak("V0001", "İstanbul", "Yalova", "29.06.2026", "09:00", "29.06.2026", "10:00"),
        _tir_bacak("V0002", "Yalova", "Eskişehir", "29.06.2026", "10:00", "29.06.2026", "13:00"),
    ])
    kapasite = KapasiteDefter({}, {"İstanbul": 5, "Yalova": 5, "Eskişehir": 5})
    _tir_dokunuslarini_isle(df, kapasite)

    assert kapasite.tir_kullanim[("Yalova", "29.06.2026")] == 2
    assert sum(kapasite.tir_kullanim.values()) == 4