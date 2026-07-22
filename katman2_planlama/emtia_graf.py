# -*- coding: utf-8 -*-
"""Katman 2 · Emtia toplulaştırma ve olay güdümlü zaman-genişletilmiş graf (§5.4).

Naif kurgu (talep = emtia) 289 hat × 7 gün × 2 slot ≈ 4.000 emtia üretir ve
MILP çözülmez. Burada aynı (varış TM, SLA bitiş anı) çiftini paylaşan
talepler tek emtia altında toplanır (~250'e iner); zaman ekseni dakika değil,
servis havuzunun (katman2_planlama/servis_havuzu.py, issue #18) ürettiği
kalkış/varış olaylarından türeyen düğümlerle temsil edilir.

MILP'in kendisi burada değil — bu modül yalnız graf + emtia tanımı +
(verilen bir çözümü) orijinal talep ID'lerine geri dağıtan ayrıştırmayı
üretir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from katman2_planlama.servis_havuzu import ServisAdayi

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

SLOT_SAATLERI: dict[str, int] = {"09:00": 9, "17:00": 17}
EPSILON = 1e-6


class AkisTutarsizligi(Exception):
    """Verilen kenar akışı, kaynak (talep) miktarlarını karşılamıyor."""


# --------------------------------------------------------------------------
# 1) Emtia tanımı + eşleme tablosu
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Emtia:
    emtia_id: str
    varis: str
    sla_bitis_ani: datetime


def _dogus_ani(tarih, slot: str) -> datetime:
    tarih_date = pd.Timestamp(tarih).date()
    return datetime.combine(tarih_date, datetime.min.time().replace(hour=SLOT_SAATLERI[slot]))


def emtia_olustur(
    talep_df: pd.DataFrame, kisitlar: "Kisitlar"
) -> tuple[tuple[Emtia, ...], pd.DataFrame]:
    """Aynı (varış TM, SLA bitiş anı) talepleri tek emtia altında toplar.

    `talep_df` şeması `kisitlar.talep` ile birebir: talep_id, tarih, cikis,
    varis, slot, toplam_desi. SLA bitiş anı = doğuş anı + sla_gun tam gün
    (§3: "1 gün = tam 24 saat") — yuvarlama burada değil, gecikme
    hesaplanırken devreye girer.

    Döner: (emtia listesi, eşleme tablosu). Eşleme tablosu kolonları:
    talep_id, emtia_id, cikis, dogus_ani, desi.
    """
    satirlar = []
    for row in talep_df.itertuples(index=False):
        dogus_ani = _dogus_ani(row.tarih, row.slot)
        sla_gun = kisitlar.sla_gun(row.cikis, row.varis)
        sla_bitis_ani = dogus_ani + timedelta(days=sla_gun)
        satirlar.append({
            "talep_id": row.talep_id,
            "cikis": row.cikis,
            "varis": row.varis,
            "dogus_ani": dogus_ani,
            "sla_bitis_ani": sla_bitis_ani,
            "desi": float(row.toplam_desi),
        })
    df = pd.DataFrame(satirlar)

    anahtarlar = (
        df[["varis", "sla_bitis_ani"]]
        .drop_duplicates()
        .sort_values(["varis", "sla_bitis_ani"])
        .reset_index(drop=True)
    )
    anahtarlar["emtia_id"] = [f"E{i + 1:05d}" for i in range(len(anahtarlar))]

    df = df.merge(anahtarlar, on=["varis", "sla_bitis_ani"], how="left")

    emtialar = tuple(
        Emtia(emtia_id=r.emtia_id, varis=r.varis, sla_bitis_ani=r.sla_bitis_ani)
        for r in anahtarlar.itertuples(index=False)
    )
    eslesme_tablosu = df[["talep_id", "emtia_id", "cikis", "dogus_ani", "desi"]].reset_index(drop=True)

    print(
        f"emtia toplulaştırma: {len(talep_df)} talep -> {len(emtialar)} emtia "
        f"(§5.4 hedefi ~250)"
    )
    return emtialar, eslesme_tablosu


# --------------------------------------------------------------------------
# 2) Zaman-genişletilmiş graf
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Dugum:
    tm: str
    an: datetime


@dataclass(frozen=True)
class Kenar:
    kaynak: Dugum
    hedef: Dugum
    tur: str  # "servis" | "bekleme"
    servis_adayi: ServisAdayi | None = None


def graf_kur(
    servis_adaylari: list[ServisAdayi], kisitlar: "Kisitlar"
) -> tuple[frozenset[Dugum], tuple[Kenar, ...]]:
    """Zaman-genişletilmiş graf: düğümler servis havuzunun kalkış/varış
    olaylarından türer (dakika ızgarası değil, §5.4). Kenarlar: her servis
    bacağı için bir 'servis' kenarı; her TM içinde ardışık anlar arasında
    bir 'bekleme' kenarı — araca maliyet yazmaz, yalnız zamanı/SLA saatini
    ilerletir (§3 "yük bedava bekler").
    """
    servis_kenarlari: list[Kenar] = []
    tm_anlari: dict[str, set[datetime]] = {}

    for aday in servis_adaylari:
        servis = aday.servis
        yuk_per_durak = {tm: aday.kapasite_desi for tm in servis.duraklar}
        for cikis_tm, varis_tm in servis.bacaklar():
            kaynak_an = servis.ziyaret_ani(cikis_tm, kisitlar, yuk_per_durak)
            hedef_an = servis.ziyaret_ani(varis_tm, kisitlar, yuk_per_durak)
            kaynak = Dugum(cikis_tm, kaynak_an)
            hedef = Dugum(varis_tm, hedef_an)
            servis_kenarlari.append(Kenar(kaynak, hedef, "servis", aday))
            tm_anlari.setdefault(cikis_tm, set()).add(kaynak_an)
            tm_anlari.setdefault(varis_tm, set()).add(hedef_an)

    bekleme_kenarlari: list[Kenar] = []
    for tm, anlar in tm_anlari.items():
        sirali = sorted(anlar)
        for onceki, sonraki in zip(sirali, sirali[1:]):
            bekleme_kenarlari.append(
                Kenar(Dugum(tm, onceki), Dugum(tm, sonraki), "bekleme", None)
            )

    tum_kenarlar = tuple(servis_kenarlari) + tuple(bekleme_kenarlari)
    dugumler = frozenset(d for kenar in tum_kenarlar for d in (kenar.kaynak, kenar.hedef))

    print(f"zaman-genişletilmiş graf: {len(dugumler)} düğüm, {len(tum_kenarlar)} kenar")
    return dugumler, tum_kenarlar


# --------------------------------------------------------------------------
# 3) Akış ayrıştırma (çözüm sonrası) — standart flow decomposition
# --------------------------------------------------------------------------

def _bacaklari_izle(
    dugum: Dugum, miktar: float, parca_id: str, kalan: dict[Kenar, float]
) -> list[dict]:
    cikan_kenarlar = sorted(
        (k for k in kalan if k.kaynak == dugum and kalan[k] > EPSILON),
        key=lambda k: (k.hedef.tm, k.hedef.an),
    )
    if not cikan_kenarlar:
        return [{"talep_id": parca_id, "desi": miktar, "bacaklar": []}]

    dallar: list[tuple[Kenar, float]] = []
    kalan_miktar = miktar
    for kenar in cikan_kenarlar:
        if kalan_miktar <= EPSILON:
            break
        pay = min(kalan_miktar, kalan[kenar])
        if pay <= EPSILON:
            continue
        kalan[kenar] -= pay
        kalan_miktar -= pay
        dallar.append((kenar, pay))

    if kalan_miktar > EPSILON:
        raise AkisTutarsizligi(
            f"{parca_id}: {miktar} desi için yeterli kenar akışı yok "
            f"({dugum.tm}, {dugum.an}) — {miktar - kalan_miktar} desi karşılandı."
        )

    bolundu = len(dallar) > 1
    sonuclar: list[dict] = []
    for i, (kenar, pay) in enumerate(dallar, start=1):
        alt_id = f"{parca_id}-{i}" if bolundu else parca_id
        for parca in _bacaklari_izle(kenar.hedef, pay, alt_id, kalan):
            parca["bacaklar"] = [kenar] + parca["bacaklar"]
            sonuclar.append(parca)
    return sonuclar


def akis_ayristir(
    emtia_id: str,
    eslesme_tablosu: pd.DataFrame,
    kenar_akislari: dict[Kenar, float],
) -> tuple[list[dict], dict[Kenar, float]]:
    """Verilen emtia-bazlı akış çözümünü (`kenar_akislari`) orijinal talep
    ID'lerine geri dağıtır (§5.4, standart "flow decomposition": her kaynak
    kendi düğümünden başlayıp akışı sinke kadar greedy izler).

    Bir düğümde tek çıkış kenarı mevcut miktarın tamamını taşıyorsa parça
    ID'si değişmez; birden fazla kenar gerekiyorsa (girdi çözümü öyle
    dağıtmışsa) parçalar 'D00001-1', 'D00001-2' olur; biri ileride tekrar
    bölünürse 'D00001-1-1' (§3 ID kuralı). Kenar akışı talebi karşılamıyorsa
    sessizce geçilmez — `AkisTutarsizligi` fırlatılır.

    `kenar_akislari` değiştirilmez (kopyası üzerinde çalışılır); döner:
    (parçalar, kalan_akislar) — ikincisi her kenarda ayrıştırma sonrası
    kalan (tüketilmemiş) akış miktarıdır; tam tüketim beklenen senaryolarda
    çağıran bunun sıfır olduğunu doğrulayabilir.
    """
    if not (eslesme_tablosu["emtia_id"] == emtia_id).all():
        raise AkisTutarsizligi(f"eslesme_tablosu {emtia_id} dışında satır içeriyor.")

    kalan = dict(kenar_akislari)
    sonuc: list[dict] = []
    for row in eslesme_tablosu.sort_values("talep_id").itertuples(index=False):
        kaynak = Dugum(row.cikis, row.dogus_ani)
        sonuc.extend(_bacaklari_izle(kaynak, row.desi, row.talep_id, kalan))
    return sonuc, kalan
