# -*- coding: utf-8 -*-
"""Spot tırsız araç yerleştirici ve elleçleme öteleyici.

Tır slot tahsisinden kalan yükü tırsız spot araçlara atar.
Elleçleme kapasitesi taşarsa düşük-SLA-baskılı yükü ertesi güne öteler.
Hiçbir yük dışarıda kalmaz; geciken yükler SLA cezasıyla taşınır.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.kiralik_placer import KapasiteDefteri
from katman2_planlama.servis import Servis, maliyet_hesapla, sla_ceza_hesapla

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar


class ElleçlemeDefteri:
    """TM–gün bazında spot elleçleme kapasitesi takibi."""

    def __init__(self, gunluk_limit: dict[str, float]) -> None:
        self._limit = gunluk_limit
        self._kullanim: dict[tuple[str, date], float] = {}

    def kalan(self, tm: str, gun: date) -> float:
        return max(0.0, self._limit.get(tm, 0.0) - self._kullanim.get((tm, gun), 0.0))

    def kullan(self, tm: str, baslangic: datetime, desi: float) -> None:
        """Elleçleme kullanımını kaydeder; gece yarısını aşarsa iki güne oransal böler."""
        dk = math.ceil(desi * config.ELLECLEME_DK_PER_DESI)
        if dk == 0:
            return
        bitis = baslangic + timedelta(minutes=dk)
        gun1 = baslangic.date()
        gun2 = bitis.date()
        if gun1 == gun2:
            self._kullanim[(tm, gun1)] = self._kullanim.get((tm, gun1), 0.0) + desi
        else:
            gece = datetime.combine(gun2, datetime.min.time())
            gun1_dk = (gece - baslangic).total_seconds() / 60
            gun2_dk = (bitis - gece).total_seconds() / 60
            self._kullanim[(tm, gun1)] = self._kullanim.get((tm, gun1), 0.0) + desi * gun1_dk / dk
            self._kullanim[(tm, gun2)] = self._kullanim.get((tm, gun2), 0.0) + desi * gun2_dk / dk


def _en_ucuz_tip(
    kisitlar: "Kisitlar", cikis: str, varis: str, _ani: datetime
) -> str:
    """Tam yük için desi başına en ucuz tırsız araç tipini döndürür."""
    tir_harici = [ad for ad in kisitlar.arac_tipleri if ad != "Tır"]

    def _cpd(ad: str) -> float:
        kap = kisitlar.arac_tipleri[ad].kapasite_desi
        return maliyet_hesapla(
            Servis(arac_tipi=ad, kiralik=False, duraklar=(cikis, varis), cikis_ani=_ani),
            {cikis: kap, varis: kap},
            kisitlar,
        ).arac_maliyeti_tl / kap

    return min(tir_harici, key=_cpd)


def _araç_sec(
    kisitlar: "Kisitlar", cikis: str, varis: str, desi: float, _ani: datetime
) -> list[tuple[str, float]]:
    """
    `desi` yük için spot araç listesi: [(arac_tipi, yuk_desi), ...].
    Tam yükler → desi başına en ucuzu; artık yük → en ucuz tek araç.
    """
    en_ucuz = _en_ucuz_tip(kisitlar, cikis, varis, _ani)
    kap = kisitlar.arac_tipleri[en_ucuz].kapasite_desi
    tam = int(desi // kap)
    artik = desi - tam * kap

    plan: list[tuple[str, float]] = [(en_ucuz, float(kap))] * tam

    if artik > 0:
        tir_harici = [ad for ad in kisitlar.arac_tipleri if ad != "Tır"]

        def _artik_mal(ad: str) -> float:
            y = min(artik, kisitlar.arac_tipleri[ad].kapasite_desi)
            return maliyet_hesapla(
                Servis(arac_tipi=ad, kiralik=False, duraklar=(cikis, varis), cikis_ani=_ani),
                {cikis: y, varis: y},
                kisitlar,
            ).arac_maliyeti_tl

        artik_tip = min(tir_harici, key=_artik_mal)
        yuklu = min(artik, kisitlar.arac_tipleri[artik_tip].kapasite_desi)
        plan.append((artik_tip, float(yuklu)))

    return plan


def spot_arac_ata(
    kisitlar: "Kisitlar",
    kalan_talep_df: pd.DataFrame,
    kapasite: KapasiteDefteri,
    tahmin_baslangic: datetime,
) -> tuple[list[Servis], pd.DataFrame, "ElleçlemeDefteri"]:
    """
    Kalan talebi spot tırsız araçlara atar.

    Elleçleme kapasitesi taşarsa 2-gün-SLA yükünü önce erteler (daha az baskılı);
    1-gün-SLA yükü da ertelenmek zorundaysa SLA cezasıyla taşınır.
    Hiçbir yük dışarıda kalmaz.

    Döndürür
    --------
    servisler   : oluşturulan Servis nesneleri
    rapor_df    : her servisin kalkış / teslim / ceza özeti
    ell_defter  : final elleçleme defteri (testler için kapasite doğrulaması)
    """
    ell = ElleçlemeDefteri(dict(kapasite.ellecleme_kalan))

    bekleyen: list[dict] = []
    for _, row in kalan_talep_df.iterrows():
        slot_h = int(str(row["slot"]).split(":")[0])
        tarih = pd.Timestamp(row["tarih"]).date()
        talep_ani = datetime(tarih.year, tarih.month, tarih.day, slot_h)
        sla_gun_val = kisitlar.sla_gun(row["cikis"], row["varis"])
        bekleyen.append({
            "cikis": row["cikis"],
            "varis": row["varis"],
            "desi": float(row["kalan_desi"]),
            "talep_ani": talep_ani,
            "sla_deadline": talep_ani + timedelta(days=sla_gun_val),
            "sla_gun": sla_gun_val,
        })

    # 1-gün SLA önce (daha baskılı) → elleçleme kapasitesini o önce kullanır
    bekleyen.sort(key=lambda x: (x["talep_ani"], x["sla_gun"]))

    servisler: list[Servis] = []
    rapor: list[dict] = []

    for _ in range(14):  # en fazla 14 gün erteleme (sonsuz döngü güvencesi)
        if not bekleyen:
            break
        siradaki: list[dict] = []

        for satir in bekleyen:
            cikis = satir["cikis"]
            varis = satir["varis"]
            desi = satir["desi"]
            talep_ani = satir["talep_ani"]
            sla_deadline = satir["sla_deadline"]
            gun_c = talep_ani.date()

            # Çıkış TM kapasitesi kontrolü
            c_kalan = ell.kalan(cikis, gun_c)
            if c_kalan <= 0.0:
                siradaki.append({**satir, "talep_ani": talep_ani + timedelta(days=1)})
                continue

            plan = _araç_sec(kisitlar, cikis, varis, min(desi, c_kalan), talep_ani)

            atanan_desi = 0.0
            ertelenen_plan_desi = 0.0
            for arac_tipi, yuk_desi in plan:
                ell_c_dk_a = math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)
                seyir_dk_a = math.ceil(kisitlar.seyir_saat(cikis, varis, arac_tipi) * 60)
                ell_v_dk_a = math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)

                kalkis = talep_ani + timedelta(minutes=ell_c_dk_a)
                varis_varisi = kalkis + timedelta(minutes=seyir_dk_a)
                teslim_ani = varis_varisi + timedelta(minutes=ell_v_dk_a)

                # Gece yarısı split: elleçleme hangi gün(ler)e ne kadar desi düşecek?
                bitis_v = varis_varisi + timedelta(minutes=ell_v_dk_a)
                gun_v1 = varis_varisi.date()
                gun_v2 = bitis_v.date()
                if gun_v1 == gun_v2:
                    v_split = {gun_v1: yuk_desi}
                else:
                    gece_v = datetime.combine(gun_v2, datetime.min.time())
                    t1 = (gece_v - varis_varisi).total_seconds() / 60
                    v_split = {
                        gun_v1: yuk_desi * t1 / ell_v_dk_a,
                        gun_v2: yuk_desi * (ell_v_dk_a - t1) / ell_v_dk_a,
                    }

                # Her iki gün için de kapasite yeterli mi?
                if any(ell.kalan(varis, g) < d for g, d in v_split.items()):
                    siradaki.append({
                        **satir,
                        "desi": yuk_desi,
                        "talep_ani": talep_ani + timedelta(days=1),
                    })
                    ertelenen_plan_desi += yuk_desi
                    continue

                ell.kullan(cikis, talep_ani, yuk_desi)
                ell.kullan(varis, varis_varisi, yuk_desi)

                servisler.append(Servis(
                    arac_tipi=arac_tipi,
                    kiralik=False,
                    duraklar=(cikis, varis),
                    cikis_ani=kalkis,
                ))

                ceza = sla_ceza_hesapla(teslim_ani, sla_deadline, yuk_desi)
                rapor.append({
                    "tarih": gun_c,
                    "cikis": cikis,
                    "varis": varis,
                    "arac_tipi": arac_tipi,
                    "yuk_desi": yuk_desi,
                    "kalkis": kalkis,
                    "teslim_ani": teslim_ani,
                    "sla_bitis": sla_deadline,
                    "ceza_tl": ceza,
                })
                atanan_desi += yuk_desi

            kalan_desi = desi - atanan_desi - ertelenen_plan_desi
            if kalan_desi > 0.0:
                siradaki.append({
                    **satir,
                    "desi": kalan_desi,
                    "talep_ani": talep_ani + timedelta(days=1),
                })

        bekleyen = siradaki
        bekleyen.sort(key=lambda x: (x["talep_ani"], x["sla_gun"]))

    # Güvenlik: 14 günden sonra hâlâ bekleyen varsa kapasite kontrolsüz zorla ata
    for satir in bekleyen:
        cikis, varis = satir["cikis"], satir["varis"]
        desi, talep_ani, sla_deadline = satir["desi"], satir["talep_ani"], satir["sla_deadline"]
        plan = _araç_sec(kisitlar, cikis, varis, desi, talep_ani)
        for arac_tipi, yuk_desi in plan:
            ell_c_dk = math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)
            seyir_dk = math.ceil(kisitlar.seyir_saat(cikis, varis, arac_tipi) * 60)
            ell_v_dk = math.ceil(yuk_desi * config.ELLECLEME_DK_PER_DESI)
            kalkis = talep_ani + timedelta(minutes=ell_c_dk)
            varis_varisi = kalkis + timedelta(minutes=seyir_dk)
            teslim_ani = varis_varisi + timedelta(minutes=ell_v_dk)
            servisler.append(Servis(
                arac_tipi=arac_tipi, kiralik=False,
                duraklar=(cikis, varis), cikis_ani=kalkis,
            ))
            ceza = sla_ceza_hesapla(teslim_ani, sla_deadline, yuk_desi)
            rapor.append({
                "tarih": talep_ani.date(), "cikis": cikis, "varis": varis,
                "arac_tipi": arac_tipi, "yuk_desi": yuk_desi,
                "kalkis": kalkis, "teslim_ani": teslim_ani,
                "sla_bitis": sla_deadline, "ceza_tl": ceza,
            })

    rapor_df = (
        pd.DataFrame(rapor)
        if rapor
        else pd.DataFrame(columns=[
            "tarih", "cikis", "varis", "arac_tipi", "yuk_desi",
            "kalkis", "teslim_ani", "sla_bitis", "ceza_tl",
        ])
    )
    return servisler, rapor_df, ell
