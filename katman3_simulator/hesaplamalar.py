import math


def ellecleme_suresi_dk(desi: int) -> int:
    """Elleçleme süresi: tavan(desi × 0.01) dakika."""
    return math.ceil(desi * 0.01)


def seyir_suresi_dk(saat: float) -> int:
    """Seyir süresi: tavan(saat × 60) dakika."""
    return math.ceil(saat * 60)


def kullanim_suresi_dk(desi: int, seyir_saat: float, bekleme_dk: int = 0) -> int:
    """Araç kullanım süresi: çıkış elleçleme + bekleme + seyir + varış elleçleme."""
    cikis_ell = ellecleme_suresi_dk(desi)
    seyir = seyir_suresi_dk(seyir_saat)
    varis_ell = ellecleme_suresi_dk(desi)
    return cikis_ell + bekleme_dk + seyir + varis_ell


def gece_yarisi_bolme(baslangic_dakika: int, sure_dk: int) -> tuple:
    """Gece yarısını aşan elleçlemeyi iki güne böler.

    baslangic_dakika: günün kaçıncı dakikasında başlıyor (0-1439).
                      Örnek: 23:30 = 23*60+30 = 1410
    sure_dk: elleçleme süresi dakika

    Döndürür: (bugun_desi_orani, yarin_desi_orani)
    """
    gece_yarisi = 1440  # 24 * 60
    bitis = baslangic_dakika + sure_dk

    if bitis <= gece_yarisi:
        return (1.0, 0.0)

    bugun_dk = gece_yarisi - baslangic_dakika
    yarin_dk = bitis - gece_yarisi
    return (bugun_dk / sure_dk, yarin_dk / sure_dk)


def sla_ceza_saat(gecikme_dk: int) -> int:
    """SLA gecikme cezası: üst tam saate yuvarla.

    1 dk gecikme = 1 saat ceza
    120 dk (2 saat) gecikme = 2 saat ceza
    140 dk (2 saat 20 dk) gecikme = 3 saat ceza
    """
    if gecikme_dk <= 0:
        return 0
    return math.ceil(gecikme_dk / 60)
