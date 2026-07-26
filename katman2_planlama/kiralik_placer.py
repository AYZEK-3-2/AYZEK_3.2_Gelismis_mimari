# -*- coding: utf-8 -*-
"""Kiralık araç yerleştirici.

14 kiralık araç her gün zorunlu olarak çıkar — 7 gün x 14 araç = 98 servis.
Rota sabit, uğrama yasak, dönüş yok.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import TYPE_CHECKING

import pandas as pd

import config
from katman2_planlama.servis import Servis, maliyet_hesapla

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

class KiralikHata(Exception):
    """Kiralık araca yasak işlem yaptırılmaya çalışıldığında atılır."""


class KapasiteDefteri:
    """TM bazında tır slotu ve elleçleme kapasitesi takibi."""

    def __init__(self, kisitlar: "Kisitlar") -> None:
        self.tir_kalan = dict(kisitlar.tir_kapasitesi)
        self.ellecleme_kalan = dict(kisitlar.ellecleme_kapasitesi)

    def tir_slot_dus(self, tm: str, adet: int = 1) -> None:
        if self.tir_kalan.get(tm, 0) < adet:
            raise KiralikHata(f"{tm} TM'sinde yeterli tır slotu yok.")
        self.tir_kalan[tm] -= adet

    def ellecleme_dus(self, tm: str, desi: float) -> None:
        self.ellecleme_kalan[tm] = self.ellecleme_kalan.get(tm, 0) - desi

def _kalkis_ve_varis(hat, tarih, baz_saat: int, yuk_desi: float, kisitlar: "Kisitlar"):
    """Bir kiralık servisin kalkış ve varış anı (araç başına yükle)."""
    yuk_per_arac = yuk_desi / hat.adet if hat.adet > 0 else 0.0
    ell_dk = math.ceil(yuk_per_arac * config.ELLECLEME_DK_PER_DESI)
    kalkis = datetime.combine(
        tarih, datetime.min.time().replace(hour=baz_saat)
    ) + timedelta(minutes=ell_dk)
    seyir_dk = math.ceil(kisitlar.seyir_saat(hat.cikis, hat.varis, hat.arac_turu) * 60)
    return kalkis, kalkis + timedelta(minutes=seyir_dk + ell_dk)


def _kiralik_gunluk_yuk(hat, tarih, tahmin_df: pd.DataFrame, kisitlar: "Kisitlar",
                        zorunlu_saat: int | None = None):
    """Bir kiralık hattın o gün taşıyacağı yük.

    Döner: (yuk_09, yuk_17, yuk_desi, desi_09, desi_17, baz_saat)

    Araç yalnızca KENDİ çıkış slotunun talebini taşır; diğer slotun kargosu o
    saatte hazır değildir (yük doğmadan araca binemez) → tamamı spot'a kalır.
    """


    maske_base = (
        (tahmin_df["tarih"].dt.date == tarih)
        & (tahmin_df["cikis"] == hat.cikis)
        & (tahmin_df["varis"] == hat.varis)
    )
    desi_09 = float(tahmin_df.loc[maske_base & (tahmin_df["slot"] == "09:00"), "toplam_desi"].sum())
    desi_17 = float(tahmin_df.loc[maske_base & (tahmin_df["slot"] == "17:00"), "toplam_desi"].sum())

    # Çıkış slotu: aracın DAHA ÇOK yük taşıyabildiği slot seçilir.
    #
    # Önceki kural "09:00'da bir miktar talep varsa 09:00'dan kalk" idi ve gerçek
    # veride çok pahalıya mal oluyordu: desinin %91'i 17:00 slotunda (mimari §4),
    # yani kiralık araç neredeyse her gün küçük 09:00 dilimini alıp kalkıyor,
    # büyük 17:00 yükü ise PARAYLA spot araçlara kalıyordu. Ölçüm — İstanbul→Yalova
    # 29.06: 09:00'da 3.518 desi, 17:00'da 43.467 desi; iki zorunlu tırın kapasitesi
    # 44.800. Araç 3.518 taşıyıp gidiyor, 43.467 desi spot'a yazılıyordu.
    #
    # Kiralık araç ZATEN çıkmak zorunda (§3: "talep yetersiz olsa bile çıkmak
    # zorunlu") — maliyeti batıktır. Taşıdığı her desi bir spot aracı ikame eder,
    # o yüzden dolu gitmesi her zaman kazançtır. Kalkış saatini biz seçiyoruz (§3).
    # Eşitlikte 09:00 tercih edilir: erken kalkış SLA açısından her zaman >= geç.
    kap = kisitlar.arac_tipleri[hat.arac_turu].kapasite_desi * hat.adet
    if zorunlu_saat is not None:
        baz_saat = zorunlu_saat
    else:
        baz_saat = 9 if min(desi_09, kap) >= min(desi_17, kap) else 17

    if baz_saat == 9:
        yuk_09, yuk_17 = min(desi_09, kap), 0.0
    else:
        yuk_09, yuk_17 = 0.0, min(desi_17, kap)

    return yuk_09, yuk_17, yuk_09 + yuk_17, desi_09, desi_17, baz_saat


def kiralik_servisleri_yerlestir(
    kisitlar: "Kisitlar",
    tahmin_df: pd.DataFrame,
    tahmin_baslangic: datetime,
) -> tuple[list[Servis], pd.DataFrame, KapasiteDefteri, float]:
    """
    Zorunlu kiralık servisleri yerleştirir (7 gün × toplam araç adedi).

    Döndürür
    --------
    servisler           : Servis nesneleri
    kalan_talep_df      : spot havuzuna geçen artık talep
    kapasite            : güncellenmiş kapasite defteri
    toplam_maliyet_tl   : sabit kiralık maliyet (TL)
    """
    kapasite = KapasiteDefteri(kisitlar)
    servisler: list[Servis] = []
    kalan_satirlar: list[dict] = []
    toplam_maliyet_tl = 0.0

    # Tır slotu — araç başınadır, yükten bağımsız
    for hat in kisitlar.kiralik_hatlar:
        if hat.arac_turu == "Tır":
            kapasite.tir_slot_dus(hat.cikis, hat.adet)
            kapasite.tir_slot_dus(hat.varis, hat.adet)

    # Kiralık tırların (TM, GÜN) bazlı gerçek dokunuşları.
    #
    # `tir_slot_dus` TM başına düz bir sayı düşer ve örtük olarak "varış aynı gün"
    # varsayar. 17:00 kalkışlarda varış çoğu zaman ERTESİ güne taşar; o zaman bir
    # TM, hem kendi o günkü kalkışlarından hem de bir önceki günün varışlarından
    # dokunuş alır ve gerçek günlük dokunuş sayısı düz rezervasyonu aşar. Gerçek
    # veride kapasite kapısı bunu yakaladı (Yalova 30.06 → 5 / 4 slot).
    # Dokunuş günü, simülatörün saydığı günle birebir olsun diye VARIŞ ANINDAN
    # (seyir + varış elleçlemesi dahil) hesaplanır.
    # Slot seçimi tır kapasitesini de gözetmek ZORUNDA. "Daha çok yük taşı" kuralı
    # tek başına araçları 17:00'a kaydırıyor, varış ertesi güne taşıyor ve iki
    # ardışık günün kiralık tırı aynı güne düşüp o TM'nin günlük slotunu aşıyor
    # (canlı testte Balıkesir 05.07 → 2/1, Tekirdağ 05.07 → 3/2). Bu, kiralık
    # araçlar ZORUNLU olduğu için sonradan telafi edilemez — seçim anında
    # kontrol edilmeli. Tercih 17:00 ama slot yetmiyorsa 09:00'a düşülür.
    secilen_saat: dict[tuple, int] = {}
    tir_dokunus: dict[tuple, int] = {}
    for gun in range(7):
        tarih = (tahmin_baslangic + timedelta(days=gun)).date()
        for hat in kisitlar.kiralik_hatlar:
            _, _, yuk_desi, _, _, tercih = _kiralik_gunluk_yuk(
                hat, tarih, tahmin_df, kisitlar
            )
            if hat.arac_turu != "Tır":
                secilen_saat[(hat, tarih)] = tercih
                continue

            # TIR için 17:00 ancak varış AYNI GÜN İÇİNDE kalıyorsa seçilir.
            #
            # Tır slotu (TM, gün) bazlıdır ve bu hatlarda kapasite zaten günlük
            # kadans kadardır (ör. Balıkesir kapasite 1, her gün 1 zorunlu tır
            # alıyor). Varış gece yarısını geçtiği anda o TM iki ardışık günün
            # tırını aynı güne alır ve slot KAÇINILMAZ olarak aşılır — kiralık
            # zorunlu olduğu için sonradan telafi de edilemez. Canlı testte
            # görüldü: 04.07 19:06 kalkış → 05.07 00:42 varış, Balıkesir 2/1.
            # "Her iki olası günü de rezerve et" denendi; daha fazla aracı
            # 09:00'a itip başka günlerde 6 aşım üretti, geri alındı.
            #
            # Varış anı yüke bağlı olduğu için TAM KAPASİTE (en geç varış)
            # üzerinden bakılır: en kötü durum aynı gün içinde kalıyorsa gerçek
            # yükle de kalır (§5.4 "süreyi asla eksik gösterme").
            kap_tam = kisitlar.arac_tipleri[hat.arac_turu].kapasite_desi * hat.adet
            for aday_saat in ([tercih] if tercih == 9 else [17, 9]):
                kalkis, varis = _kalkis_ve_varis(
                    hat, tarih, aday_saat, kap_tam, kisitlar
                )
                if aday_saat == 9 or varis.date() == kalkis.date():
                    secilen_saat[(hat, tarih)] = aday_saat
                    _, gercek_varis = _kalkis_ve_varis(
                        hat, tarih,
                        aday_saat,
                        _kiralik_gunluk_yuk(
                            hat, tarih, tahmin_df, kisitlar, zorunlu_saat=aday_saat
                        )[2],
                        kisitlar,
                    )
                    anahtar_c = (hat.cikis, kalkis.date())
                    anahtar_v = (hat.varis, gercek_varis.date())
                    tir_dokunus[anahtar_c] = tir_dokunus.get(anahtar_c, 0) + hat.adet
                    tir_dokunus[anahtar_v] = tir_dokunus.get(anahtar_v, 0) + hat.adet
                    break
    kapasite.tir_dokunus = tir_dokunus

    # Elleçleme rezervasyonu — kiralık aracın GERÇEKTE taşıyacağı yük üzerinden.
    #
    # Önceden burada tam araç kapasitesi (kapasite_desi × adet) rezerve ediliyordu.
    # "Muhafazakâr" diye not düşülmüştü ama gerçek veride muhafazakâr değil,
    # YIKICI: Kocaeli'de 12 kiralık hattın rezervasyonu 91.200 desi, TM'nin günlük
    # elleçleme kapasitesi ise 89.262 — kalan NEGATİFE düşüyor, `ElleçlemeDefteri`
    # onu 0'a kırpıyor ve spot Kocaeli'den hiçbir gün hiçbir şey taşıyamıyor.
    # Sonuç: Kocaeli çıkışlı yükün tamamı 14 gün ötelenip zorla atanıyordu —
    # 120 satır, sadece 39.960 desi için 5.039.490 TL SLA cezası (toplamın %6,1'i).
    #
    # Defter TM başına TEK bir günlük sayı tuttuğu için günlerin MAKSİMUMU rezerve
    # edilir: hiçbir günde eksik rezervasyon olmaz (spot fazla yükleyemez), ama
    # kullanılmayan kapasite de boşuna kilitlenmez.
    gunluk_yukler: dict[tuple, float] = {}
    for gun in range(7):
        tarih = (tahmin_baslangic + timedelta(days=gun)).date()
        for hat in kisitlar.kiralik_hatlar:
            gunluk_yukler[(hat, tarih)] = _kiralik_gunluk_yuk(
                hat, tarih, tahmin_df, kisitlar,
                zorunlu_saat=secilen_saat[(hat, tarih)],
            )[2]

    for hat in kisitlar.kiralik_hatlar:
        en_yuksek = max(
            gunluk_yukler[(hat, (tahmin_baslangic + timedelta(days=g)).date())]
            for g in range(7)
        )
        kapasite.ellecleme_dus(hat.cikis, en_yuksek)
        kapasite.ellecleme_dus(hat.varis, en_yuksek)

    # Rezervasyon yine de kapasiteyi aşıyorsa spot o TM'de tamamen kilitlenir;
    # sessizce sıfıra kırpılmasındansa görünür olsun.
    for tm, kalan in kapasite.ellecleme_kalan.items():
        if kalan < 0:
            print(f"  uyari: {tm} elleçleme kapasitesi kiralık rezervasyonuyla "
                  f"tükendi ({kalan:,.0f} desi acik) — spot o TM'den tasiyamaz.")

    for gun in range(7):
        tarih = (tahmin_baslangic + timedelta(days=gun)).date()

        for hat in kisitlar.kiralik_hatlar:
            arac_obj = kisitlar.arac_tipleri[hat.arac_turu]

            yuk_09, yuk_17, yuk_desi, desi_09, desi_17, baz_saat = (
                _kiralik_gunluk_yuk(
                    hat, tarih, tahmin_df, kisitlar,
                    zorunlu_saat=secilen_saat[(hat, tarih)],
                )
            )
            kalan_09 = desi_09 - yuk_09
            kalan_17 = desi_17 - yuk_17

            # Çıkış elleçlemesi araç başınadır: her araç yalnız kendi payını yükler.
            # Toplam yük (yuk_desi) üzerinden hesaplarsak adet>1 hatlarda çıkış saati
            # gereksiz gecikir ve aşağıdaki maliyet hesabıyla (yuk_per_arac) çelişir.
            yuk_per_arac = yuk_desi / hat.adet if hat.adet > 0 else 0.0
            ellecleme_dk = math.ceil(yuk_per_arac * config.ELLECLEME_DK_PER_DESI)
            cikis_ani = datetime.combine(tarih, datetime.min.time().replace(hour=baz_saat)) \
                + timedelta(minutes=ellecleme_dk)

            for _ in range(hat.adet):
                servis = Servis(
                    arac_tipi=hat.arac_turu,
                    kiralik=True,
                    duraklar=(hat.cikis, hat.varis),
                    cikis_ani=cikis_ani,
                )
                servisler.append(servis)
                yuk_per_durak = {hat.cikis: yuk_per_arac, hat.varis: yuk_per_arac}
                toplam_maliyet_tl += maliyet_hesapla(servis, yuk_per_durak, kisitlar).arac_maliyeti_tl

            for slot, kalan in (("09:00", kalan_09), ("17:00", kalan_17)):
                if kalan > 0.0:
                    kalan_satirlar.append({
                        "cikis": hat.cikis,
                        "varis": hat.varis,
                        "tarih": tarih,
                        "slot": slot,
                        "kalan_desi": kalan,
                    })

    # Kiralık olmayan rotaları kalan'a ekle (tir/spot karşılasın)
    kiralik_rotalar = {(hat.cikis, hat.varis) for hat in kisitlar.kiralik_hatlar}
    for _, row in tahmin_df.iterrows():
        if (row["cikis"], row["varis"]) not in kiralik_rotalar:
            desi = float(row.get("toplam_desi", 0.0))
            if desi > 0:
                kalan_satirlar.append({
                    "cikis": row["cikis"],
                    "varis": row["varis"],
                    "tarih": pd.Timestamp(row["tarih"]).date(),
                    "slot": str(row["slot"]),
                    "kalan_desi": desi,
                })

    kalan_talep_df = (
        pd.DataFrame(kalan_satirlar)
        if kalan_satirlar
        else pd.DataFrame(columns=["cikis", "varis", "tarih", "slot", "kalan_desi"])
    )
    return servisler, kalan_talep_df, kapasite, toplam_maliyet_tl
    