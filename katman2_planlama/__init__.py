# -*- coding: utf-8 -*-
"""Katman 2: greedy 3-katmanlı planlama (issue #12-#16).

Kiralık → Tır slot → Spot sırasıyla talep karşılanır.
Hiçbir talep dışarıda kalmaz; kuyruğa giren her talep ya normal araçla
ya da geç-tarihli yedek araçla plan dosyasına yazılır.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir
from katman2_planlama.tir_slot_tahsis import tir_slot_tahsis
from katman2_planlama.spot_placer import spot_arac_ata
from katman2_planlama.plan_yazici import plan_yaz, AracPlan, BacakAtama, TalepAtama
from katman2_planlama.servis import Servis, maliyet_hesapla, sla_ceza_hesapla

GUN_SAYISI = 7


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


def _gercek_yukte_en_ucuz_tip(
    cikis: str, varis: str, mevcut_tip: str, desi_gercek: float, kisitlar,
) -> str:
    """Aracın GERÇEK yüküne göre en ucuz araç tipini seçer (yalnız spot).

    Tip seçimi (`spot_placer._araç_sec`, `tir_slot_tahsis`) araç oluşturulurken,
    yani o aracın gerçekte ne taşıyacağı bilinmeden yapılıyor: tam kapasite
    varsayımıyla "desi başına en ucuz" tip seçiliyor. Atama bittiğinde araç
    çoğu zaman ondan az taşıyor ve seçim artık optimal olmayabiliyor — küçük
    yükte saatlik kirası düşük bir araç neredeyse her zaman daha ucuz.
    Gerçek veride ölçüldü: 3.779 spot aracın 137'si daha ucuz bir tiple
    taşınabiliyordu, fazladan maliyet 1.679.867 TL.

    Kurallar
    --------
    * Yalnız yükü TAŞIYABİLEN tipler değerlendirilir.
    * Tır'a YÜKSELTME yapılmaz — tır dokunuşu (TM, gün) slotu tüketir ve o slot
      bütçesi `tir_slot_tahsis`te zaten dağıtılmıştır; sonradan tır eklemek
      kısıt sızdırır. Tır'dan DÜŞÜRMEK serbesttir (slot boşaltır, kısıt gevşer)
      ve §10'un "tır <100 km hatta çıkıyorsa şüphe" sağlık testini de rahatlatır.
    * Elleçleme süresi tipe değil desiye bağlı olduğu için TM-gün elleçleme
      muhasebesi bu değişimden etkilenmez.
    """
    aday_tipler = [
        ad for ad, at in kisitlar.arac_tipleri.items()
        if at.kapasite_desi >= desi_gercek and (ad != "Tır" or mevcut_tip == "Tır")
    ]
    if not aday_tipler:
        return mevcut_tip

    def _mal(ad: str) -> float:
        return _maliyet(cikis, varis, ad, False, datetime.min, desi_gercek, kisitlar)

    en_ucuz = min(aday_tipler, key=_mal)
    return en_ucuz if _mal(en_ucuz) < _mal(mevcut_tip) - 0.01 else mevcut_tip


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
    Her aracı, kendi hattında ve kendi kalkışından ÖNCE doğmuş taleplerle,
    `yuk_desi` kapasitesi dolana kadar yükler.

    İki kural taşıyor:

    1. **Yük doğmadan araca binemez.** Bir talep ancak `dogus_ani <= cikis_ani`
       ise o araca yüklenebilir. Önceden bu hiç kontrol edilmiyordu: kuyruk
       (tarih, slot) sırasına, araçlar ise yerleştirme sırasına göre eşleşiyordu
       ve ikisi örtüşmüyordu — gerçek veride planın %4,1'i (182 satır, 671.231
       desi) yükü doğmadan taşıyordu, en uç örnekte 5 gün 15 saat erken. Bu
       fiziksel olarak geçersiz satır üretmektir (MVP'yi öldüren hata sınıfı) ve
       hiçbir kapı yakalamıyordu; `katman3_simulator.dogrula_dogus_ani` artık
       yakalıyor.

    2. **Araç başına birden fazla talep.** Önceden her araç kuyruğun başından
       TEK bir ısırık alıp duruyor, kalan kapasitesi çöpe gidiyordu. Gerekçe
       olarak "dogrula_zaman_cakismasi birden fazla satırı aynı araçta farklı
       bacak sayar" yazıyordu; o sınırlama sonradan giderildi (simulator.py
       çakışma kontrolü artık BACAK bazında tekilleştiriyor), yorum bayat
       kalmıştı. Kısıtın maliyeti ölçüldü: gerçek veride hiçbir hatta araç
       eksiği olmamasına rağmen 608 talep (1,32M desi, tüm talebin %17,8'i)
       araçlara sığmıyor, 54 araç ise tamamen boş kalıyordu; sığmayanlar +14
       gün ötelenip 186,5M TL SLA cezası üretiyordu.

    Eşleştirme hat bazında, ZAMAN SIRASINA göre yapılır: araçlar kalkış anına,
    talepler doğuş anına göre sıralanır; her araç, kalkışına kadar doğmuş
    talepler arasından en eskisini önce alır (en eski yük en çok gecikme
    riskindedir).

    Returns
    -------
    atamalar  : [(servis_bilgisi, [TalepAtama, ...]), ...]  ← araç başına 0..n talep
    atanmamis : hiçbir araca sığmayan (desi > 1e-9) talep dicts
    """
    # Hat bazında talep listesi — sıfır ve negatif desiyi atla
    hat_talepleri: dict[tuple, list[dict]] = {}
    sirali = tahmin_df.sort_values(
        ["tarih", "slot", "cikis", "varis"], kind="stable"
    )
    for _, row in sirali.iterrows():
        kalan = max(0.0, float(row["tahmin_desi"]))
        if kalan < 1e-9:
            continue
        key = (str(row["cikis"]), str(row["varis"]))
        hat_talepleri.setdefault(key, []).append({
            "talep_id": str(row["talep_id"]),
            "tarih": pd.Timestamp(row["tarih"]),
            "slot": str(row["slot"]),
            "kalan": kalan,
            "cikis": str(row["cikis"]),
            "varis": str(row["varis"]),
            "dogus_ani": _dogus_ani(row["tarih"], str(row["slot"])),
        })

    # Araçları hatlarına göre grupla; her hat içinde kalkış anına göre sırala.
    # `servis_bilgileri` içindeki orijinal sıra korunmalı (çağıran atamaları
    # sırayla eşleştiriyor), o yüzden indeksle çalışılır.
    hat_araclari: dict[tuple, list[int]] = {}
    for i, sb in enumerate(servis_bilgileri):
        hat_araclari.setdefault((sb["cikis"], sb["varis"]), []).append(i)
    for idxler in hat_araclari.values():
        idxler.sort(key=lambda i: servis_bilgileri[i]["cikis_ani"])

    arac_talepleri: dict[int, list[TalepAtama]] = {}

    for key, araclar in hat_araclari.items():
        talepler = hat_talepleri.get(key)
        if not talepler:
            continue
        sla_gun = kisitlar.sla_gun(key[0], key[1])

        for arac_idx in araclar:
            sb = servis_bilgileri[arac_idx]
            bos_kapasite = float(sb["yuk_desi"])
            cikis_ani = sb["cikis_ani"]

            for t in talepler:
                if bos_kapasite < 1e-9:
                    break
                if t["kalan"] < 1e-9:
                    continue
                # Kural 1: yük doğmadan binemez
                if t["dogus_ani"] > cikis_ani:
                    continue

                alinacak = min(t["kalan"], bos_kapasite)
                t["kalan"] -= alinacak
                bos_kapasite -= alinacak

                arac_talepleri.setdefault(arac_idx, []).append(TalepAtama(
                    talep_id=t["talep_id"],
                    desi=alinacak,
                    son_bacak=True,
                    # plan_uret ana döngüsünde varis_ani bilindiğinde hesaplanır
                    sla_ceza=0.0,
                    sla_bitis=t["dogus_ani"] + timedelta(days=sla_gun),
                ))

    atamalar = [
        (sb, arac_talepleri.get(i, []))
        for i, sb in enumerate(servis_bilgileri)
    ]

    atanmamis: list[dict] = []
    for talepler in hat_talepleri.values():
        for t in talepler:
            if t["kalan"] > 1e-9:
                atanmamis.append({
                    k: v for k, v in t.items() if k != "dogus_ani"
                })

    return atamalar, atanmamis


def _milp_talep_df(tahmin: pd.DataFrame) -> pd.DataFrame:
    """`tahmin` -> `kayan_pencere_coz`/`lns_iyilestir`in beklediği talep şeması."""
    return pd.DataFrame({
        "talep_id": tahmin["talep_id"],
        "tarih": pd.to_datetime(tahmin["tarih"]),
        "cikis": tahmin["cikis"],
        "varis": tahmin["varis"],
        "slot": tahmin["slot"],
        "toplam_desi": tahmin["tahmin_desi"].astype("float64").clip(lower=0.0),
    })


def plan_uret_full(
    veri,
    tahmin,
    cikti_dizini: str | None = None,
    *,
    milp_dakika: float = 10.0,
    lns_dakika: float = 0.0,
) -> str:
    """MILP (kayan pencere) + opsiyonel LNS plan üretici — `--full` yolu.

    `kayan_pencere_coz` her pencerede MILP'i greedy'nin GERÇEK maliyetiyle
    kıyaslar ve ucuz olanı commit eder; MILP çözüm bulamazsa (UNKNOWN/INFEASIBLE)
    o pencere greedy'ye düşer. Yani bu yol hiçbir koşulda greedy'den kötü bir
    plan üretmez — en kötü ihtimalle greedy'nin aynısını, daha uzun sürede üretir.

    `lns_dakika > 0` ise sonuca bir yık-onar turu uygulanır. LNS'in simülatör
    kapısı `kisitlar.talep`e bakar; o yüzden buraya TAHMİN tablosuyla değiştirilmiş
    bir `Kisitlar` verilir (katman3_simulator.dogrula_ve_yaz ile aynı sözleşme) —
    ham `veri` verilseydi kapının SLA kontrolü tahmin ID'lerini (D70001+) tarihsel
    tabloda bulamayıp SESSİZCE atlardı.
    """
    import dataclasses

    from katman2_planlama.kayan_pencere import kayan_pencere_coz
    from katman2_planlama.lns import lns_iyilestir

    cikti_dizini = cikti_dizini or str(config.CIKTI_KLASORU)
    Path(cikti_dizini).mkdir(parents=True, exist_ok=True)
    dosya_yolu = str(Path(cikti_dizini) / "Tasima-plani.xlsx")

    talep_df = _milp_talep_df(tahmin)
    pencere_butcesi = milp_dakika * 60.0 / GUN_SAYISI

    sonuc = kayan_pencere_coz(
        veri, talep_df, config.TAHMIN_BASLANGIC,
        pencere_zaman_limit_sn=pencere_butcesi,
    )
    print(f"MILP kayan pencere: {sonuc.toplam_sure_sn:.1f} sn")
    if not sonuc.pencere_raporu.empty:
        secim = sonuc.pencere_raporu["secilen"].value_counts().to_dict()
        print(f"  pencere seçimi: {secim}")

    arac_planlari = sonuc.arac_planlari

    if lns_dakika > 0:
        veri_lns = dataclasses.replace(veri, talep=talep_df)
        lns = lns_iyilestir(
            veri_lns, talep_df, config.TAHMIN_BASLANGIC, arac_planlari,
            sure_butce_sn=lns_dakika * 60.0,
        )
        print(f"LNS: {lns.baslangic_maliyet_tl:,.2f} -> {lns.son_maliyet_tl:,.2f} TL "
              f"({lns.toplam_sure_sn:.1f} sn)")
        arac_planlari = lns.arac_planlari

    plan_yaz(arac_planlari, dosya_yolu)
    print(f"Plan hazir: {len(arac_planlari)} arac")
    return dosya_yolu


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

        # Tip seçimi gerçek yük bilinmeden yapılmıştı; şimdi biliyoruz.
        # Kiralık aracın türü sözleşmeyle sabit, ona dokunulmaz.
        if not kiralik:
            arac_tipi = _gercek_yukte_en_ucuz_tip(
                cikis, varis, arac_tipi, desi_gercek, kisitlar
            )

        seyir_dk = math.ceil(
            kisitlar.seyir_saat(cikis, varis, arac_tipi) * 60
        )
        ell_v_dk = math.ceil(desi_gercek * config.ELLECLEME_DK_PER_DESI - config.TAVAN_TOLERANSI_DK)
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
        ell_v_dk = math.ceil(desi * config.ELLECLEME_DK_PER_DESI - config.TAVAN_TOLERANSI_DK)
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
