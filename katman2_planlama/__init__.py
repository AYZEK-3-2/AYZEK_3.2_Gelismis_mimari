# -*- coding: utf-8 -*-
"""Katman 2: greedy 3-katmanlı planlama (issue #12-#16).

Kiralık → Tır slot → Spot sırasıyla talep karşılanır.
Hiçbir talep dışarıda kalmaz; kuyruğa giren her talep ya normal araçla
ya da geç-tarihli yedek araçla plan dosyasına yazılır.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir
from katman2_planlama.tir_slot_tahsis import tir_slot_tahsis
from katman2_planlama.spot_placer import spot_arac_ata
from katman2_planlama.plan_yazici import plan_yaz, AracPlan, BacakAtama, TalepAtama
from katman2_planlama.servis import Servis, maliyet_hesapla, sla_ceza_hesapla


def _dogus_ani(tarih, slot: str) -> datetime:
    saat = int(str(slot).split(":")[0])
    return datetime.combine(pd.Timestamp(tarih).date(), datetime.min.time().replace(hour=saat))


def _spot_arac_tipi_sec(desi: float, kisitlar) -> str:
    """Desi'yi taşıyabilecek en küçük tırsız araç tipini döndürür."""
    tir_harici = sorted(
        [ad for ad in kisitlar.arac_tipleri if ad != "Tır"],
        key=lambda ad: kisitlar.arac_tipleri[ad].kapasite_desi,
    )
    for ad in tir_harici:
        if kisitlar.arac_tipleri[ad].kapasite_desi >= desi:
            return ad
    return tir_harici[-1]


def _maliyet(cikis: str, varis: str, arac_tipi: str, kiralik: bool,
             cikis_ani: datetime, desi_gercek: float, kisitlar) -> float:
    """Gerçek taşınan desi'den araç maliyeti hesapla (simülatörle birebir).

    int() KESMESİ YOK: katman3_simulator._hesapla_maliyet de "Taşınan Desi"yi
    float olarak toplar (kesirli desi kesmenin kuruş kapısını kırdığı, daha önce
    canlı testle bulunmuş bir bug — bkz. issue #21). Buradaki hesap onunla
    "simülatörle birebir" olmalı, o yüzden aynı şekilde kesilmemiş float kullanır.
    """
    servis = Servis(
        arac_tipi=arac_tipi,
        kiralik=kiralik,
        duraklar=(cikis, varis),
        cikis_ani=cikis_ani,
    )
    return maliyet_hesapla(
        servis,
        {cikis: desi_gercek, varis: desi_gercek},
        kisitlar,
    ).arac_maliyeti_tl


def _talepleri_ata(
    servis_bilgileri: list[dict],
    tahmin_df: pd.DataFrame,
    kisitlar,
) -> tuple[list[tuple[dict, list]], list[dict]]:
    """
    Her aracı (cikis, varis) kuyruğundaki tek bir talep dilimiyle eşleştir.

    Araç başına TEK talep — dogrula_zaman_cakismasi birden fazla satırı
    aynı araçta farklı "bacak" sayar ve yanlış hata verir. Bu kısıt gereği
    her araç kuyruğun başındaki talep öğesinden en fazla yuk_desi kadar
    tek bir ısırık alır; fazlası bir sonraki araca kalır.

    Returns
    -------
    atamalar  : [(servis_bilgisi, [TalepAtama]), ...]   ← liste uzunluğu 0 ya da 1
    atanmamis : kuyrukta kalan (desi > 1e-9) talep dicts
    """
    # Kuyruğu oluştur — sıfır ve negatif desiyi atla
    kuyruklar: dict[tuple, deque] = {}
    sirali = tahmin_df.sort_values(
        ["tarih", "slot", "cikis", "varis"], kind="stable"
    )
    for _, row in sirali.iterrows():
        kalan = max(0.0, float(row["tahmin_desi"]))
        if kalan < 1e-9:
            continue
        key = (str(row["cikis"]), str(row["varis"]))
        if key not in kuyruklar:
            kuyruklar[key] = deque()
        kuyruklar[key].append({
            "talep_id": str(row["talep_id"]),
            "tarih": pd.Timestamp(row["tarih"]),
            "slot": str(row["slot"]),
            "kalan": kalan,
            "cikis": str(row["cikis"]),
            "varis": str(row["varis"]),
        })

    atamalar: list[tuple[dict, list]] = []

    for sb in servis_bilgileri:
        key = (sb["cikis"], sb["varis"])
        q = kuyruklar.get(key)

        # Tükenmiş (kalan<epsilon) girişleri temizle
        if q:
            while q and q[0]["kalan"] < 1e-9:
                q.popleft()

        if not q:
            atamalar.append((sb, []))
            continue

        # Tek ısırık: kuyruğun başından en fazla yuk_desi al
        t = q[0]
        alinacak = min(t["kalan"], float(sb["yuk_desi"]))
        t["kalan"] -= alinacak
        if t["kalan"] < 1e-9:
            q.popleft()

        sla_bitis = _dogus_ani(t["tarih"], t["slot"]) + timedelta(
            days=kisitlar.sla_gun(t["cikis"], t["varis"])
        )
        talep = TalepAtama(
            talep_id=t["talep_id"],
            desi=alinacak,
            son_bacak=True,
            sla_ceza=0.0,   # plan_uret ana döngüsünde varis_ani bilindiğinde hesaplanır
            sla_bitis=sla_bitis,
        )
        atamalar.append((sb, [talep]))

    # Hâlâ kuyrukta kalan talepler → atanmamis
    atanmamis: list[dict] = []
    for q in kuyruklar.values():
        for t in q:
            if t["kalan"] > 1e-9:
                atanmamis.append(dict(t))

    return atamalar, atanmamis


def plan_uret(veri, tahmin, cikti_dizini: str | None = None) -> str:
    """
    Greedy 3-katmanlı plan üretici.

    Parameters
    ----------
    veri    : Kisitlar nesnesi (veriyi_yukle() çıktısı)
    tahmin  : talep_id_ata() çıktısı DataFrame
              (sütunlar: tarih, cikis, varis, slot, tahmin_desi, talep_id)
    cikti_dizini : çıktı klasörü (varsayılan config.CIKTI_KLASORU)

    Returns
    -------
    Yazılan Tasima-plani.xlsx dosyasının tam yolu.
    """
    kisitlar = veri
    cikti_dizini = cikti_dizini or str(config.CIKTI_KLASORU)
    Path(cikti_dizini).mkdir(parents=True, exist_ok=True)
    dosya_yolu = str(Path(cikti_dizini) / "Tasima-plani.xlsx")

    # tahmin_df hazırla — kiralik_placer "toplam_desi" ve Timestamp tarih bekler
    tahmin_df = tahmin.copy()
    tahmin_df["tarih"] = pd.to_datetime(tahmin_df["tarih"])
    tahmin_df["toplam_desi"] = (
        tahmin_df["tahmin_desi"].astype("float64").clip(lower=0.0)
    )

    baslangic = config.TAHMIN_BASLANGIC

    # ── Katman A: Kiralık araç yerleştirme ──────────────────────────────────
    kiralik_servisler, kalan1, kapasite, _ = kiralik_servisleri_yerlestir(
        kisitlar, tahmin_df, baslangic
    )

    # ── Katman B: Tır slot tahsisi ──────────────────────────────────────────
    tir_servisler, kalan2, kapasite, _tir_rapor = tir_slot_tahsis(
        kisitlar, kalan1, kapasite
    )

    # ── Katman C: Spot araç ataması ─────────────────────────────────────────
    spot_servisler, spot_rapor, _ell = spot_arac_ata(
        kisitlar, kalan2, kapasite, baslangic
    )

    # ── servis_bilgileri listesi ─────────────────────────────────────────────
    # Her giriş: araç meta-bilgisi + queue'dan ne kadar kapasiteyle drain edeceği
    servis_bilgileri: list[dict] = []

    # Kiralık — kapasite_desi = tam yük (queue doğal drain eder)
    for srv in kiralik_servisler:
        kap = float(kisitlar.arac_tipleri[srv.arac_tipi].kapasite_desi)
        servis_bilgileri.append({
            "cikis": srv.duraklar[0],
            "varis": srv.duraklar[1],
            "arac_tipi": srv.arac_tipi,
            "kiralik": True,
            "cikis_ani": srv.cikis_ani,
            "yuk_desi": kap,
        })

    # Tır (spot) — bir tır kapasitesi
    tir_kap = float(kisitlar.arac_tipleri["Tır"].kapasite_desi)
    for srv in tir_servisler:
        servis_bilgileri.append({
            "cikis": srv.duraklar[0],
            "varis": srv.duraklar[1],
            "arac_tipi": "Tır",
            "kiralik": False,
            "cikis_ani": srv.cikis_ani,
            "yuk_desi": tir_kap,
        })

    # Spot — rapordaki yuk_desi
    for srv, (_, satir) in zip(spot_servisler, spot_rapor.iterrows()):
        servis_bilgileri.append({
            "cikis": srv.duraklar[0],
            "varis": srv.duraklar[1],
            "arac_tipi": srv.arac_tipi,
            "kiralik": False,
            "cikis_ani": srv.cikis_ani,
            "yuk_desi": float(satir["yuk_desi"]),
        })

    # ── Talepleri araçlara ata ───────────────────────────────────────────────
    atamalar, atanmamis = _talepleri_ata(servis_bilgileri, tahmin_df, kisitlar)

    # ── AracPlan listesi ─────────────────────────────────────────────────────
    arac_planlari: list[AracPlan] = []

    for sb, talepler in atamalar:
        if not talepler:
            continue  # boş araç (kiralık rotada sıfır talep) → plan'a yazılmaz

        desi_gercek = sum(t.desi for t in talepler)  # int() kesmesi YOK, bkz. _maliyet

        cikis = sb["cikis"]
        varis = sb["varis"]
        arac_tipi = sb["arac_tipi"]
        kiralik = sb["kiralik"]
        cikis_ani = sb["cikis_ani"]

        seyir_dk = math.ceil(
            kisitlar.seyir_saat(cikis, varis, arac_tipi) * 60
        )
        ell_v_dk = math.ceil(desi_gercek * config.ELLECLEME_DK_PER_DESI)
        varis_ani = cikis_ani + timedelta(minutes=seyir_dk + ell_v_dk)

        # SLA cezası — varis_ani ancak burada bilindiği için (_talepleri_ata
        # yalnız araç eşleşmesine bakar, zamanlamayı bilmez) gerçek gecikme
        # burada hesaplanır; _talepleri_ata yalnız sla_bitis'i (kök talebin
        # doğuş anı + sla_gun) önceden hesaplayıp taşımıştı.
        for talep in talepler:
            if talep.sla_bitis is not None:
                talep.sla_ceza = sla_ceza_hesapla(varis_ani, talep.sla_bitis, talep.desi)

        mal = _maliyet(cikis, varis, arac_tipi, kiralik, cikis_ani, desi_gercek, kisitlar)

        bacak = BacakAtama(
            cikis=cikis,
            varis=varis,
            cikis_ani=cikis_ani,
            varis_ani=varis_ani,
            seyir_dk=seyir_dk,
            talepler=talepler,
        )
        arac_planlari.append(AracPlan(
            arac_tipi=arac_tipi,
            kiralik=kiralik,
            bacaklar=[bacak],
            toplam_maliyet=mal,
        ))

    # ── Atanamamış talepleri yedek geç-tarihli araçlarla karşıla ────────────
    # Planlama dönemi 7 gün; +14 gün → elleçleme kapasitesi o dönemde boş.
    if atanmamis:
        print(f"  uyari: {len(atanmamis)} talep normal araclara sigmadi, "
              f"gec-tarihli araclara aktariliyor.")

    for t in atanmamis:
        cikis = t["cikis"]
        varis = t["varis"]
        desi = t["kalan"]
        arac_tipi = _spot_arac_tipi_sec(desi, kisitlar)

        late_cikis = (
            t["tarih"] + timedelta(days=14)
        ).replace(hour=9, minute=0, second=0, microsecond=0).to_pydatetime()

        seyir_dk = math.ceil(
            kisitlar.seyir_saat(cikis, varis, arac_tipi) * 60
        )
        ell_v_dk = math.ceil(desi * config.ELLECLEME_DK_PER_DESI)
        late_varis = late_cikis + timedelta(minutes=seyir_dk + ell_v_dk)

        mal = _maliyet(cikis, varis, arac_tipi, False, late_cikis, desi, kisitlar)

        # Bu yük yapısal olarak geç (14 gün ötelenmiş) — SLA cezası kaçınılmaz
        # biçimde büyük olacaktır; 0 yazmak muhasebe invariantını (§8.2) yanlış
        # gösterir. sla_bitis, kök talebin GERÇEK (ötelenmemiş) doğuş anına göre.
        sla_bitis = _dogus_ani(t["tarih"], t["slot"]) + timedelta(
            days=kisitlar.sla_gun(cikis, varis)
        )
        sla_ceza = sla_ceza_hesapla(late_varis, sla_bitis, desi)

        bacak = BacakAtama(
            cikis=cikis,
            varis=varis,
            cikis_ani=late_cikis,
            varis_ani=late_varis,
            seyir_dk=seyir_dk,
            talepler=[TalepAtama(
                talep_id=t["talep_id"],
                desi=desi,
                son_bacak=True,
                sla_ceza=sla_ceza,
                sla_bitis=sla_bitis,
            )],
        )
        arac_planlari.append(AracPlan(
            arac_tipi=arac_tipi,
            kiralik=False,
            bacaklar=[bacak],
            toplam_maliyet=mal,
        ))

    # ── Bölünmüş kök talepleri suffix'le (D00001-1, D00001-2, ...) ──────────
    # Greedy'nin "tek ısırık" mekanizması (+ 14 gün geç-tarihli devir) BÜYÜK
    # bir talebi aynı kök ID ile (suffix'siz) birden fazla satıra/araca
    # dağıtabilir. Her bite KENDİ varış anına göre kendi SLA cezasını taşıdığı
    # için (biri zamanında, biri geç kalabilir) aynı kök ID birden fazla
    # satırda sıfırdan farklı ceza taşıyabilir — bu, muhasebe invariantını
    # (§8.2, issue #22 canlı testinde bulundu) ihlal eder. Fiilen bölünen
    # talepler §3'ün "Talep bölme: Serbest. D00001-1, D00001-2" kuralına göre
    # suffix'lenir (yalnız GERÇEKTEN bölünenler — tek satırda kalanlar
    # suffix'siz kalır) ki her biri bağımsız bir parça olarak muhasebeleşsin.
    kok_toplam: dict[str, int] = {}
    for arac in arac_planlari:
        for bacak in arac.bacaklar:
            for talep in bacak.talepler:
                kok_toplam[talep.talep_id] = kok_toplam.get(talep.talep_id, 0) + 1

    kok_sayaci: dict[str, int] = {}
    for arac in arac_planlari:
        for bacak in arac.bacaklar:
            for talep in bacak.talepler:
                kok = talep.talep_id
                if kok_toplam[kok] > 1:
                    kok_sayaci[kok] = kok_sayaci.get(kok, 0) + 1
                    talep.talep_id = f"{kok}-{kok_sayaci[kok]}"

    # ── Plan dosyasına yaz ───────────────────────────────────────────────────
    plan_yaz(arac_planlari, dosya_yolu)
    print(f"Plan hazir: {len(arac_planlari)} arac")
    return dosya_yolu
