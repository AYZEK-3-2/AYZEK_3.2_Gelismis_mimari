# -*- coding: utf-8 -*-
"""Tır slot tahsis modülü.

Kiralık seferler tüketildikten sonra kalan spot tır slotlarını,
en yüksek tasarruf sağlayan (gün, hat) çiftlerine öncelikli olarak dağıtır.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.kiralik_placer import KapasiteDefteri
from katman2_planlama.servis import Servis, maliyet_hesapla

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

_MIN_KM = 100  # Bu altındaki hatlarda tır elleçleme cezası yüzünden dezavantajlı

def _tasarruf_per_desi(
    kisitlar: "Kisitlar",
    cikis: str,
    varis: str,
    slot: str,
    tir_kap: int,
    alternatifler: list[str],
) -> float:
    """
    Bir tam tır yükünü (tir_kap desi) tır yerine en ucuz alternatifle taşımanın
    desi başına maliyet farkını verir. Pozitif → tır avantajlı.
    Elleçleme dahil TAM formülle hesaplanır.
    """
    baz_saat = int(slot.split(":")[0])
    _ani = datetime(2026, 1, 1, baz_saat)  # tarih maliyet hesabını etkilemiyor

    tir_servis = Servis(
        arac_tipi="Tır", kiralik=False, duraklar=(cikis, varis), cikis_ani=_ani
    )
    tir_maliyet = maliyet_hesapla(
        tir_servis, {cikis: tir_kap, varis: tir_kap}, kisitlar
    ).arac_maliyeti_tl

    en_ucuz = float("inf")
    for ad in alternatifler:
        arac_kap = kisitlar.arac_tipleri[ad].kapasite_desi
        arac_sayisi = math.ceil(tir_kap / arac_kap)
        tek_maliyet = maliyet_hesapla(
            Servis(arac_tipi=ad, kiralik=False, duraklar=(cikis, varis), cikis_ani=_ani),
            {cikis: arac_kap, varis: arac_kap},
            kisitlar,
        ).arac_maliyeti_tl
        if tek_maliyet * arac_sayisi < en_ucuz:
            en_ucuz = tek_maliyet * arac_sayisi

    return (en_ucuz - tir_maliyet) / tir_kap

def tir_slot_tahsis(
    kisitlar: "Kisitlar",
    kalan_talep_df: pd.DataFrame,
    kapasite: KapasiteDefteri,
) -> tuple[list[Servis], pd.DataFrame, KapasiteDefteri, pd.DataFrame]:
    """
    Spot tır slotlarını tasarrufa göre (gün, hat) çiftlerine greedy tahsis eder.

    Döndürür
    --------
    tir_servisleri  : oluşturulan spot tır Servis nesneleri
    kalan_talep_df  : tır'ın karşılamadığı artık talep
    kapasite        : günlük tır bütçesi (değişmez — slot günlük sıfırlanır);
                      tahsis (TM, gün) bazında yapılır, per-gün kalan rapor_df'de
    rapor_df        : gün x hat → tır sefer sayısı + o günkü kalan slot özeti
    """
    tir_kap = kisitlar.arac_tipleri["Tır"].kapasite_desi
    alternatifler = [ad for ad in kisitlar.arac_tipleri if ad != "Tır"]

    df = kalan_talep_df.copy()

    # --- 1. AŞAMA: filtrele ve tasarrufu hesapla ---
    adaylar: list[dict] = []
    for idx, row in df.iterrows():
        cikis, varis = row["cikis"], row["varis"]

        if kisitlar.mesafe_km(cikis, varis) < _MIN_KM:
            continue
        if kapasite.tir_kalan.get(cikis, 0) == 0 or kapasite.tir_kalan.get(varis, 0) == 0:
            continue

        tasarruf = _tasarruf_per_desi(
            kisitlar, cikis, varis, row["slot"], tir_kap, alternatifler
        )
        if tasarruf <= 0:
            continue

        adaylar.append({
            "idx": idx,
            "tarih": row["tarih"],
            "cikis": cikis,
            "varis": varis,
            "slot": row["slot"],
            "tasarruf": tasarruf,
        })

    # --- 2. AŞAMA: tasarrufa göre büyükten küçüğe sırala ---
    adaylar.sort(key=lambda x: x["tasarruf"], reverse=True)

    # --- 3. AŞAMA: greedy ata ---
    tir_servisleri: list[Servis] = []
    rapor_satirlar: list[dict] = []

    # Tır slotu GÜNLÜK kapasitedir (00:00'da sıfırlanır). Bütçe (TM, gün)
    # anahtarlı tutulmalı; tek per-TM sayaç 7 güne yayılırsa haftalık tahsis
    # tek günlük bütçeyle sınırlanıp ~7× eksik kalır. Her (TM, gün) için başlangıç
    # bütçesi = kiralıktan sonra kalan günlük slot (kapasite.tir_kalan[tm]).
    gun_slot: dict[tuple, int] = {}

    # Kiralık tırların GERÇEK (TM, gün) dokunuşları — `kapasite.tir_kalan` düz
    # bir TM sayacıdır ve "varış aynı gün" varsayar; 17:00 kalkışlarda varış
    # ertesi güne taşınca o günün bütçesi olduğundan fazla görünür (canlı testte
    # Yalova 30.06 → 5/4 slot). Varsa gün bazlı gerçek dokunuş kullanılır.
    kiralik_dokunus = getattr(kapasite, "tir_dokunus", None)

    def _slot_kalan(tm: str, gun) -> int:
        anahtar = (tm, gun)
        if anahtar not in gun_slot:
            if kiralik_dokunus is not None:
                tam_kapasite = kisitlar.tir_kapasitesi.get(tm, 0)
                gun_slot[anahtar] = max(
                    0, tam_kapasite - kiralik_dokunus.get(anahtar, 0)
                )
            else:
                gun_slot[anahtar] = kapasite.tir_kalan.get(tm, 0)
        return gun_slot[anahtar]

    # Elleçleme bütçesi (TM, gün). Bu katman tır atarken TM-gün elleçleme
    # kapasitesini TÜKETİYOR ama önceden bunu hiç hesaba katmıyordu: ne kendi
    # tahsisini sınırlıyor ne de `kapasite`den düşüyordu, dolayısıyla `spot_placer`
    # zaten tırların yediği kapasiteyi boşmuş gibi görüyordu. Hata uzun süre
    # görünmedi çünkü `kiralik_placer` tam araç kapasitesi rezerve ederek açığı
    # tesadüfen kapatıyordu; o rezervasyon gerçek yüke indirilince kapasite kapısı
    # 7 TM-günde aşım yakaladı (İstanbul 30.06: 410.600 / 394.786 desi).
    gun_ell: dict[tuple, float] = {}

    def _ell_kalan(tm: str, gun) -> float:
        anahtar = (tm, gun)
        if anahtar not in gun_ell:
            gun_ell[anahtar] = max(0.0, float(kapasite.ellecleme_kalan.get(tm, 0.0)))
        return gun_ell[anahtar]

    for aday in adaylar:
        cikis, varis = aday["cikis"], aday["varis"]
        tarih = aday["tarih"]
        slot = aday["slot"]

        baz_saat_on = int(slot.split(":")[0])
        kalkis_on = datetime.combine(
            tarih, datetime.min.time().replace(hour=baz_saat_on)
        )
        # Varış GÜNÜ kalkış gününden farklı olabilir (17:00 kalkışlarda çoğunlukla
        # farklıdır) — slot o zaman VARIŞ gününde tükenir. Önceden her iki uç da
        # kalkış gününe yazılıyordu ve son günlerde kapasite kapısı aşım yakalıyordu
        # (Balıkesir 05.07 → 2/1). Elleçleme tam tır kapasitesiyle, yani en geç
        # varışla hesaplanır (§5.4 "süreyi asla eksik gösterme").
        _ell_tam = math.ceil(tir_kap * config.ELLECLEME_DK_PER_DESI)
        _seyir = math.ceil(kisitlar.seyir_saat(cikis, varis, "Tır") * 60)
        varis_gun = (
            kalkis_on + timedelta(minutes=_ell_tam + _seyir + _ell_tam)
        ).date()

        slot_c = _slot_kalan(cikis, tarih)
        slot_v = _slot_kalan(varis, varis_gun)
        if slot_c == 0 or slot_v == 0:
            continue

        kalan_desi = float(df.at[aday["idx"], "kalan_desi"])
        if kalan_desi <= 0:
            continue

        # Taşınabilecek desi: slot bütçesi VE iki uçtaki elleçleme bütçesi kadar
        slot_limitli = min(slot_c, slot_v) * tir_kap
        tasinan = min(
            kalan_desi, slot_limitli,
            _ell_kalan(cikis, tarih), _ell_kalan(varis, varis_gun),
        )
        if tasinan <= 0:
            continue

        tir_sayisi = min(math.ceil(tasinan / tir_kap), slot_c, slot_v)

        cikis_ani = kalkis_on

        for _ in range(tir_sayisi):
            tir_servisleri.append(Servis(
                arac_tipi="Tır",
                kiralik=False,
                duraklar=(cikis, varis),
                cikis_ani=cikis_ani,
            ))
        gun_slot[(cikis, tarih)] -= tir_sayisi
        gun_slot[(varis, varis_gun)] -= tir_sayisi
        gun_ell[(cikis, tarih)] -= tasinan
        gun_ell[(varis, varis_gun)] -= tasinan

        df.at[aday["idx"], "kalan_desi"] = max(0.0, kalan_desi - tasinan)

        rapor_satirlar.append({
            "tarih": tarih,
            "cikis": cikis,
            "varis": varis,
            "slot": slot,
            "tir_sayisi": tir_sayisi,
            "slot_sonrasi_cikis": gun_slot[(cikis, tarih)],
            "slot_sonrasi_varis": gun_slot[(varis, varis_gun)],
        })

    # NOT: tırların yediği elleçleme `kapasite`den KALICI olarak düşülmez.
    # `KapasiteDefteri.ellecleme_kalan` TM başına TEK bir GÜNLÜK sayıdır; buradaki
    # kullanım ise (TM, gün) bazlıdır. Günlerin maksimumunu düşmek o TM'nin
    # BÜTÜN günlerini kalıcı olarak kısar ve `spot_placer`ı aç bırakır — canlı
    # testte tam olarak bu oldu: tek bir tır 3.000 desi taşıyınca A'nın günlük
    # bütçesi her gün için sıfırlandı ve kalan yük 14 gün ötelendi. (Aynı hata
    # kiralık rezervasyonunda da vardı, bkz. kiralik_placer.)
    #
    # Mimari kararı: erken katmanlar (kiralık/tır/spot) FİLOYU BOYUTLANDIRIR,
    # kapasiteyi gerçek yükle uygulayan tek yer `_talepleri_ata`dır (§ katman2
    # __init__). Buradaki `gun_ell` yalnız bu katmanın KENDİ tahsisini makul
    # tutar; fazla üretilen araç zaten yüksüz kalır ve plana yazılmaz.
    #
    # Yine de tırların (TM, gün) bazındaki kullanımı `spot_placer`a AKTARILIR —
    # gün bazlı olduğu için hiçbir günü haksız yere kısmaz, ama spot'un filoyu
    # gerçekçi boyutlandırmasını sağlar.
    kapasite.tir_ellecleme_kullanim = {
        anahtar: max(0.0, float(kapasite.ellecleme_kalan.get(anahtar[0], 0.0))) - kalan
        for anahtar, kalan in gun_ell.items()
    }

    # --- 4. AŞAMA: çıktıları hazırla ---
    kalan_df = df[df["kalan_desi"] > 0].copy().reset_index(drop=True)
    rapor_df = (
        pd.DataFrame(rapor_satirlar)
        if rapor_satirlar
        else pd.DataFrame(columns=[
            "tarih", "cikis", "varis", "slot",
            "tir_sayisi", "slot_sonrasi_cikis", "slot_sonrasi_varis",
        ])
    )

    return tir_servisleri, kalan_df, kapasite, rapor_df