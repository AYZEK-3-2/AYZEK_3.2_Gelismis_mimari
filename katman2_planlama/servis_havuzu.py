# -*- coding: utf-8 -*-
"""Katman 2 · Servis havuzu üreticisi (mimari §5.3).

Optimizatör (sonraki issue: set-partitioning MILP) yalnız kendisine sunulan
adaylar arasından seçim yapar; bu modül o adayları üretir. Zor kararların
çoğu burada filtrelerle alınır: tır yalnız direkt gider, konsolidasyon küçük
araçların işidir (mimari §4.1, §4.3). Kiralık servisler #13'ten geliyor ve
havuza zorunlu (seçim değişkeni değil, veri) olarak ekleniyor.

Kalkış anı: her (gün, slot) için TEK nokta — talep doğuş anı + o araç
tipinin TAM KAPASİTE varsayımıyla elleçleme süresi. Bu, `kiralik_placer.py`
ile aynı ilke (§5.4 "tam kapasite varsayımı") ve candidate patlamasını
kontrol altında tutuyor; gerçek yük MILP çözümünden sonra post-pass'te
düzeltilecek (§5.4), bu modülün çıktısı yalnız referans/aday niteliğinde.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.kiralik_placer import kiralik_servisleri_yerlestir
from katman2_planlama.servis import Servis, maliyet_hesapla

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

KUCUK_ARAC_TIPLERI: tuple[str, ...] = ("Kamyon", "Hafif Kamyon", "Kamyonet")
GUN_SAYISI = 7
SLOT_SAATLERI: dict[str, int] = {"09:00": 9, "17:00": 17}
HAVUZ_HEDEF_UST_SINIR = 30_000


@dataclass(frozen=True)
class ServisAdayi:
    """Havuzdaki bir aday: fiziksel rota + tam kapasite varsayımıyla referans maliyet."""
    servis: Servis
    referans_maliyet_tl: float
    referans_kullanim_dk: int
    kapasite_desi: int
    zorunlu: bool  # kiralık servisler: x[s] sabit, budamadan muaf (§5.3)


@dataclass(frozen=True)
class HavuzSonucu:
    adaylar: tuple[ServisAdayi, ...]
    rapor: pd.DataFrame
    uretim_suresi_sn: float


def havuz_uret(
    kisitlar: "Kisitlar",
    tahmin_df: pd.DataFrame,
    tahmin_baslangic: datetime,
    *,
    sapma_katsayisi: float = 1.3,
    kucuk_arac_max_durak: int = 3,
    ara_durak_max_sayi: int | None = 1,
    tir_serbest: bool = False,
    baskinlik_budamasi: bool = True,
) -> HavuzSonucu:
    """Katman 2'nin MILP'e sunacağı aday servis havuzunu üretir.

    Parametreler filtre gevşetme anahtarlarıdır (LNS aşamasında, §5.5,
    kıt slotlu ara TM'lerde zincirleme fırsatı için `tir_serbest=True`,
    `ara_durak_max_sayi=None` ya da `baskinlik_budamasi=False` ile daha
    geniş bir havuz istenebilir).
    """
    t0 = time.perf_counter()
    adaylar: list[ServisAdayi] = []

    # 1) Kiralık servisler — zorunlu, seçim değişkeni değil veri (§5.3)
    kiralik_servisler, _kalan_talep_df, _kapasite, _kiralik_maliyet_tl = (
        kiralik_servisleri_yerlestir(kisitlar, tahmin_df, tahmin_baslangic)
    )
    for servis in kiralik_servisler:
        kapasite = kisitlar.arac_tipleri[servis.arac_tipi].kapasite_desi
        sonuc = maliyet_hesapla(
            servis,
            {tm: kapasite for tm in servis.duraklar},
            kisitlar,
        )
        adaylar.append(ServisAdayi(
            servis=servis,
            referans_maliyet_tl=sonuc.arac_maliyeti_tl,
            referans_kullanim_dk=sonuc.kullanim_suresi_dk,
            kapasite_desi=kapasite,
            zorunlu=True,
        ))

    # 2) Spot adaylar — tır (yalnız direkt) + küçük araçlar (direkt + ≤1 ara durak)
    for gun in range(GUN_SAYISI):
        tarih = (tahmin_baslangic + timedelta(days=gun)).date()
        for cikis, varis in kisitlar.aktif_hatlar:
            adaylar.extend(_tir_adaylari(kisitlar, cikis, varis, tarih, tir_serbest))
            adaylar.extend(_kucuk_arac_adaylari(
                kisitlar, cikis, varis, tarih,
                sapma_katsayisi=sapma_katsayisi,
                max_durak=kucuk_arac_max_durak,
                ara_durak_max_sayi=ara_durak_max_sayi,
            ))

    if baskinlik_budamasi:
        adaylar = _baskinlik_buda(adaylar)

    rapor = _rapor_uret(adaylar)
    uretim_suresi_sn = time.perf_counter() - t0

    if len(adaylar) > HAVUZ_HEDEF_UST_SINIR:
        print(
            f"UYARI: havuz {len(adaylar)} aday içeriyor — "
            f"hedef {HAVUZ_HEDEF_UST_SINIR} altı (§5.3)."
        )

    return HavuzSonucu(
        adaylar=tuple(adaylar),
        rapor=rapor,
        uretim_suresi_sn=uretim_suresi_sn,
    )


def _kalkis_ani(tarih, slot_saat: int, arac_tipi: str, kisitlar: "Kisitlar") -> datetime:
    """Talep doğuş anı + tam kapasite elleçleme süresi (§5.4 tam kapasite varsayımı).

    Dakika bazlı ızgara değil, olay bazlı tek nokta — `kiralik_placer.py` ile
    aynı ilke.
    """
    kapasite = kisitlar.arac_tipleri[arac_tipi].kapasite_desi
    ellecleme_dk = math.ceil(kapasite * config.ELLECLEME_DK_PER_DESI)
    baslangic = datetime.combine(tarih, datetime.min.time().replace(hour=slot_saat))
    return baslangic + timedelta(minutes=ellecleme_dk)


def _tir_uygun_mu(kisitlar: "Kisitlar", cikis: str, varis: str, tir_serbest: bool) -> bool:
    if tir_serbest:
        return True
    return (
        kisitlar.tir_kapasitesi.get(cikis, 0) > 0
        and kisitlar.tir_kapasitesi.get(varis, 0) > 0
    )


def _tir_adaylari(
    kisitlar: "Kisitlar", cikis: str, varis: str, tarih, tir_serbest: bool
) -> list[ServisAdayi]:
    """Tır → yalnız 2 durak (direkt); tır kapasitesi 0 olan TM'lerde üretilmez (§4.1)."""
    if not _tir_uygun_mu(kisitlar, cikis, varis, tir_serbest):
        return []

    kapasite = kisitlar.arac_tipleri["Tır"].kapasite_desi
    adaylar = []
    for slot_saat in SLOT_SAATLERI.values():
        cikis_ani = _kalkis_ani(tarih, slot_saat, "Tır", kisitlar)
        servis = Servis(
            arac_tipi="Tır", kiralik=False, duraklar=(cikis, varis), cikis_ani=cikis_ani,
        )
        sonuc = maliyet_hesapla(servis, {cikis: kapasite, varis: kapasite}, kisitlar)
        adaylar.append(ServisAdayi(
            servis=servis,
            referans_maliyet_tl=sonuc.arac_maliyeti_tl,
            referans_kullanim_dk=sonuc.kullanim_suresi_dk,
            kapasite_desi=kapasite,
            zorunlu=False,
        ))
    return adaylar


def _ara_durak_adaylari(
    kisitlar: "Kisitlar", cikis: str, varis: str, sapma_katsayisi: float,
    max_sayi: int | None = None,
) -> list[str]:
    """Sapma ≤ direkt mesafe × sapma_katsayisi olan konsolidasyon ara durakları.

    `max_sayi` verilirse yalnız en az sapmalı (en yakın) `max_sayi` durak
    döner — uzun hatlarda sapma sınırını sağlayan TM sayısı çok yüksek
    olabiliyor (ör. 30+) ve bu, havuzu 30 bin hedefinin çok üzerine taşıyor
    (§5.3 "kontrolsüz büyürse... çözücü boğulur"). Baskınlık budaması farklı
    ara durakları karşılaştırmaz (her biri farklı `duraklar` demeti), bu
    yüzden sınırlama burada, üretim aşamasında yapılmalı.
    """
    direkt_km = kisitlar.mesafe_km(cikis, varis)
    adaylar = []
    for m in kisitlar.transfer_merkezleri:
        if m in (cikis, varis):
            continue
        if not (kisitlar.hat_var_mi(cikis, m) and kisitlar.hat_var_mi(m, varis)):
            continue
        toplam_km = kisitlar.mesafe_km(cikis, m) + kisitlar.mesafe_km(m, varis)
        if toplam_km <= sapma_katsayisi * direkt_km:
            adaylar.append((toplam_km, m))
    adaylar.sort(key=lambda x: x[0])
    if max_sayi is not None:
        adaylar = adaylar[:max_sayi]
    return [m for _, m in adaylar]


def _kucuk_arac_adaylari(
    kisitlar: "Kisitlar", cikis: str, varis: str, tarih,
    sapma_katsayisi: float, max_durak: int, ara_durak_max_sayi: int | None = 1,
) -> list[ServisAdayi]:
    """Küçük araçlar → direkt (2 durak) + ≤1 ara durak (3 durak); §4.1, §4.3."""
    adaylar: list[ServisAdayi] = []
    ara_duraklar = (
        _ara_durak_adaylari(kisitlar, cikis, varis, sapma_katsayisi, ara_durak_max_sayi)
        if max_durak >= 3
        else []
    )

    for arac_tipi in KUCUK_ARAC_TIPLERI:
        kapasite = kisitlar.arac_tipleri[arac_tipi].kapasite_desi
        for slot_saat in SLOT_SAATLERI.values():
            cikis_ani = _kalkis_ani(tarih, slot_saat, arac_tipi, kisitlar)

            # Direkt (2 durak)
            servis = Servis(
                arac_tipi=arac_tipi, kiralik=False, duraklar=(cikis, varis),
                cikis_ani=cikis_ani,
            )
            sonuc = maliyet_hesapla(servis, {cikis: kapasite, varis: kapasite}, kisitlar)
            adaylar.append(ServisAdayi(
                servis=servis,
                referans_maliyet_tl=sonuc.arac_maliyeti_tl,
                referans_kullanim_dk=sonuc.kullanim_suresi_dk,
                kapasite_desi=kapasite,
                zorunlu=False,
            ))

            # 3 durak (O, ara, D) — ara durakta konservatif üst sınır: aracın
            # tamamı boşalıp tamamı yeniden yüklenir varsayımı (2×kapasite);
            # süreyi asla eksik göstermemek için (§5.4 ile aynı ilke).
            for ara in ara_duraklar:
                servis3 = Servis(
                    arac_tipi=arac_tipi, kiralik=False, duraklar=(cikis, ara, varis),
                    cikis_ani=cikis_ani,
                )
                yuk = {cikis: kapasite, ara: kapasite * 2, varis: kapasite}
                sonuc3 = maliyet_hesapla(servis3, yuk, kisitlar)
                adaylar.append(ServisAdayi(
                    servis=servis3,
                    referans_maliyet_tl=sonuc3.arac_maliyeti_tl,
                    referans_kullanim_dk=sonuc3.kullanim_suresi_dk,
                    kapasite_desi=kapasite,
                    zorunlu=False,
                ))
    return adaylar


def _baskinlik_buda(adaylar: list[ServisAdayi]) -> list[ServisAdayi]:
    """Aynı hat-gün-pencerede maliyetçe ezilen araç tipleri elenir.

    Grup anahtarı: (rota, gün) — aynı fiziksel rotayı aynı gün için üreten
    farklı araç tipi adayları karşılaştırılır. `referans_maliyet_tl` daha
    yüksek VE `kapasite_desi` daha düşük (ya da eşit, en az birinde kesin
    kötü) bir aday, aynı grupta ondan iyi bir alternatif varsa elenir.
    Zorunlu (kiralık) adaylar budamadan muaftır — x[s] sabittir, seçim
    değişkeni değildir (§5.3).
    """
    gruplar: dict[tuple, list[ServisAdayi]] = {}
    for aday in adaylar:
        anahtar = (aday.servis.duraklar, aday.servis.cikis_ani.date())
        gruplar.setdefault(anahtar, []).append(aday)

    sonuc: list[ServisAdayi] = []
    for grup in gruplar.values():
        for aday in grup:
            if aday.zorunlu:
                sonuc.append(aday)
                continue
            baskin_var = any(
                digeri is not aday
                and digeri.referans_maliyet_tl <= aday.referans_maliyet_tl
                and digeri.kapasite_desi >= aday.kapasite_desi
                and (
                    digeri.referans_maliyet_tl < aday.referans_maliyet_tl
                    or digeri.kapasite_desi > aday.kapasite_desi
                )
                for digeri in grup
            )
            if not baskin_var:
                sonuc.append(aday)
    return sonuc


def _rapor_uret(adaylar: list[ServisAdayi]) -> pd.DataFrame:
    """Aday sayısı hat/gün/tip kırılımıyla (§5.3 havuz raporu)."""
    if not adaylar:
        return pd.DataFrame(columns=["cikis", "varis", "gun", "arac_tipi", "aday_sayisi"])

    satirlar = [
        {
            "cikis": aday.servis.duraklar[0],
            "varis": aday.servis.duraklar[-1],
            "gun": aday.servis.cikis_ani.date(),
            "arac_tipi": aday.servis.arac_tipi,
        }
        for aday in adaylar
    ]
    return (
        pd.DataFrame(satirlar)
        .groupby(["cikis", "varis", "gun", "arac_tipi"])
        .size()
        .reset_index(name="aday_sayisi")
    )
