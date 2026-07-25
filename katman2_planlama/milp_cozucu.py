# -*- coding: utf-8 -*-
"""Katman 2 · Set-partitioning MILP çözücü (mimari §5.4).

`servis_havuzu.havuz_uret` (#18) aday servisleri (`x[s]`'in alanı), `emtia_graf` (#19) emtia
toplulaştırmasını + zaman-genişletilmiş grafı üretir. Bu modül ikisi arasındaki modeli kurar:
hangi servislerin kaç kez çalışacağına (`x`) ve her emtianın grafta hangi kenarlardan akacağına
(`f`) karar veren, sabit servis maliyeti + yük-bağımlı elleçleme maliyeti + SLA cezasını minimize
eden CP-SAT modeli.

Kapsam dışı (ayrı issue): gerçek yükle zaman/kalkış düzeltmesi (post-pass) ve
`plan_yazici.AracPlan`'a dönüştürme. Bu modülün çıktısı `CozumSonucu.kenar_akislari` —
`emtia_graf.akis_ayristir` ile talep ID'lerine geri dağıtılmaya hazır emtia-bazlı akış.

Ölçek notu (§5.4): `f[emtia, kenar]` her emtia için yalnızca zamanla ilgili kenarlarla
sınırlandırılır (`_ilgili_kenarlar`) — tam "kayan pencere" değil, ama 1 günlük dilim ve mini
örnekler için değişken sayısını kontrol altında tutan ucuz bir filtre. Çok günlük/haftalık ölçek
ayrı bir performans issue'sudur.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from ortools.sat.python import cp_model

import config
from katman2_planlama.emtia_graf import Dugum, Emtia, Kenar
from katman2_planlama.servis import maliyet_hesapla
from katman2_planlama.servis_havuzu import ServisAdayi

if TYPE_CHECKING:
    from katman0_veri.kisitlar import Kisitlar

# CP-SAT yalnız tam sayı katsayı kabul eder. Desi ölçeği config.MILP_DESI_OLCEK (akış/kapasite
# kısıtlarının hassasiyeti); para ölçeği yalnızca amaç fonksiyonu katsayılarının yuvarlamada
# kaybolmaması için burada, modül içi bir hassasiyet detayı (raporlanan TL değerleri çözümden
# sonra float olarak yeniden hesaplanır, bu ölçekle taşınmaz).
_PARA_OLCEK = 100_000

# Gece yarısını aşan elleçleme işlemlerinin gün payı oranları için hassasiyet (binde);
# CP-SAT tam sayı katsayı istediği için oran (0..1) burada tam sayıya yuvarlanır.
_ORAN_OLCEK = 1_000


class MilpCozumHatasi(Exception):
    """Model kurulurken veya çözülürken giderilemez bir tutarsızlık bulunduğunda atılır."""


@dataclass(frozen=True)
class CozumSonucu:
    x: dict[ServisAdayi, int]
    kenar_akislari: dict[str, dict[Kenar, float]]  # emtia_id -> {kenar: desi}
    sabit_maliyet_tl: float
    degisken_ellecleme_tl: float
    sla_ceza_tl: float
    toplam_maliyet_tl: float
    durum: str
    cozum_suresi_sn: float
    gap: float | None


def _sabit_kisim_tl(aday: ServisAdayi, kisitlar: "Kisitlar") -> float:
    """Yükten bağımsız kısım: seyir süresi × saatlik kira + km × km ücreti.

    `maliyet_hesapla`'ya boş yük verilirse her durakta elleçleme süresi 0 çıkar; dönen
    `arac_maliyeti_tl` tam olarak §5.4'ün "sabit kısım" tanımına eşittir.
    """
    return maliyet_hesapla(aday.servis, {}, kisitlar).arac_maliyeti_tl


def _degisken_katsayi_tl_per_desi(aday: ServisAdayi, kisitlar: "Kisitlar") -> float:
    """Bir servis-kenarından geçen desi başına elleçleme maliyeti.

    Her servis-kenarı tam 2 dokunuş taşır (kaynak yükleme + hedef indirme) — `Servis.duraklar`
    tekrar içeremediği için 3+ duraklı bir serviste de ara durağın "indir+yükle"si iki ayrı
    bacağın (kenarın) katsayılarının toplamından otomatik çıkar.
    """
    arac = kisitlar.arac_tipleri[aday.servis.arac_tipi]
    saatlik = arac.kiralik_saatlik_tl if aday.servis.kiralik else arac.spot_saatlik_tl
    return 2 * saatlik * config.ELLECLEME_DK_PER_DESI / 60.0


def _ceza_katsayi_tl_per_desi(dugum: Dugum, sla_bitis_ani) -> float:
    if dugum.an <= sla_bitis_ani:
        return 0.0
    gecikme_saat = math.ceil((dugum.an - sla_bitis_ani).total_seconds() / 3600.0)
    return gecikme_saat * config.SLA_CEZA_TL_PER_DESI_SAAT


def _gun_paylari(baslangic: datetime, bitis: datetime) -> dict:
    """Bir elleçleme işleminin [baslangic, bitis) penceresini güne(lere) dağıtır (§3).

    Aynı gün içindeyse tek güne 1.0 oranla; gece yarısını aşıyorsa iki güne, o güne
    düşen dakika oranıyla döner (örn. 23:30'da başlayan 100 dk'lık işlem: 30dk/100dk
    bugüne, 70dk/100dk yarına — altın vektör 3, `test_altin_vektorler.py`'deki
    `gece_yarisi_bolme` ile aynı ilke). İşlem süresi (elleçleme, en büyük araç
    kapasitesinde bile ~4 saat) tek bir gece yarısından fazlasını aşamaz.
    """
    if baslangic.date() == bitis.date():
        return {baslangic.date(): 1.0}
    toplam_dk = (bitis - baslangic).total_seconds() / 60.0
    gece = datetime.combine(bitis.date(), datetime.min.time())
    gun1_dk = (gece - baslangic).total_seconds() / 60.0
    gun2_dk = toplam_dk - gun1_dk
    return {baslangic.date(): gun1_dk / toplam_dk, bitis.date(): gun2_dk / toplam_dk}


def _ilgili_kenarlar(
    emtia: Emtia, en_erken_dogus, kenarlar: tuple[Kenar, ...]
) -> list[Kenar]:
    """Zaman penceresi dışındaki kenarları eler (ölçek filtresi, bkz. modül docstring)."""
    ust_sinir = emtia.sla_bitis_ani + timedelta(days=config.MILP_MAX_GECIKME_GUN)
    return [
        kenar for kenar in kenarlar
        if en_erken_dogus <= kenar.kaynak.an <= ust_sinir
    ]


def milp_coz(
    kisitlar: "Kisitlar",
    servis_adaylari: tuple[ServisAdayi, ...],
    emtialar: tuple[Emtia, ...],
    eslesme_tablosu: pd.DataFrame,
    kenarlar: tuple[Kenar, ...],
    *,
    zaman_limit_sn: float = config.MILP_ZAMAN_LIMIT_SN,
    warm_start: dict[ServisAdayi, int] | None = None,
) -> CozumSonucu:
    """Set-partitioning MILP'i kurar ve CP-SAT ile çözer (mimari §5.4).

    Parametreler
    ------------
    servis_adaylari : `servis_havuzu.havuz_uret(...).adaylar` — `x[s]`'in alanı.
    emtialar, eslesme_tablosu, kenarlar : `emtia_graf.emtia_olustur` / `graf_kur` çıktıları.
    warm_start : greedy taban çizgisinden türetilmiş `{ServisAdayi: sayı}` ipucu (opsiyonel).
    """
    t0 = time.perf_counter()
    olcek = config.MILP_DESI_OLCEK
    model = cp_model.CpModel()
    emtia_by_id: dict[str, Emtia] = {e.emtia_id: e for e in emtialar}

    # `ServisAdayi`/`Kenar` frozen dataclass oldukları için değerce eşit iki nesne (ör. aynı
    # hatta aynı anda kalkan N adet kiralık araç — `kiralik_servisleri_yerlestir` her biri için
    # yapısal olarak özdeş bir `Servis` üretir) eşit hash'e sahip olur. `servis_adaylari` ve
    # `kenarlar` içinde bu şekilde tekrarlanan (değerce eşit) girdiler olabilir; `dict[ServisAdayi,...]`
    # / `dict[(emtia,Kenar),...]` anahtarlarında bunlar birbirini ezer. Çözüm: adayları değere göre
    # SAYARAK tekilleştir — "x[s] = verilen sayı" (§5.4 kısıt 6) tam olarak bu sayımdır; kenarları da
    # tekil kümeye indir (aynı fiziksel bacağın tekrar eden kopyaları — kapasite artık `x[s]` üstünden
    # doğru sayılıyor, kenarın kaç kez listede geçtiği önemli değil).
    sayimlar = Counter(servis_adaylari)
    essiz_adaylar = list(sayimlar.keys())
    kenarlar = tuple(dict.fromkeys(kenarlar))

    # --- 1) x[s] -------------------------------------------------------------------------
    toplam_desi = float(eslesme_tablosu["desi"].sum())
    x: dict[ServisAdayi, cp_model.IntVar] = {}
    for i, aday in enumerate(essiz_adaylar):
        sayim = sayimlar[aday]
        if aday.zorunlu:
            x[aday] = model.NewConstant(sayim)
        else:
            ust_sinir = max(sayim, math.ceil(toplam_desi / aday.kapasite_desi))
            # Değişken adı `id(aday)` (bellek adresi) DEĞİL, sıra indeksiyle — id()
            # koşudan koşuya rastgele değişir (ASLR), model proto'sunu (ve CP-SAT'ın
            # üzerinde çalıştığı iç temsili) farklılaştırıp determinizmi bozar; bu
            # canlı testle ölçülüp doğrulandı.
            x[aday] = model.NewIntVar(0, ust_sinir, f"x_{i}")

    # --- 2) f[emtia, kenar] — yalnızca zamanla ilgili kenarlarda ------------------------
    en_erken_dogus: dict[str, object] = (
        eslesme_tablosu.groupby("emtia_id")["dogus_ani"].min().to_dict()
    )
    emtia_toplam_desi: dict[str, float] = (
        eslesme_tablosu.groupby("emtia_id")["desi"].sum().to_dict()
    )
    injeksiyon: dict[tuple[str, str, object], float] = (
        eslesme_tablosu.groupby(["emtia_id", "cikis", "dogus_ani"])["desi"].sum().to_dict()
    )

    # Emtianın doğuş anı, hiçbir servis adayının tam da o dakika kalkmaması yüzünden
    # `graf_kur`'un ürettiği düğüm kümesinde hiç yer almayabilir (kalkış anı = doğuş anı +
    # tam-kapasite elleçleme süresi, servis_havuzu §5.3). Bu durumda enjeksiyon düğümü hiçbir
    # kenara değmez ve yapay bir infeasible ortaya çıkar. Çözüm: doğuş anından, o TM'de o
    # emtia için ilgili en erken kalkış anına sıfır maliyetli bir "bekleme" kenarı ekle (§3
    # "yük bedava bekler") — geri kalan bekleme zinciri `graf_kur`'un ürettiği ardışık
    # bekleme kenarlarından zaten geliyor.
    f: dict[tuple[str, Kenar], cp_model.IntVar] = {}
    emtia_kenarlari: dict[str, list[Kenar]] = {}
    for emtia in emtialar:
        ilgili = list(_ilgili_kenarlar(emtia, en_erken_dogus[emtia.emtia_id], kenarlar))
        kaynak_zamanlari_by_tm: dict[str, set] = {}
        mevcut_dugumler: set[Dugum] = set()
        for k in ilgili:
            kaynak_zamanlari_by_tm.setdefault(k.kaynak.tm, set()).add(k.kaynak.an)
            mevcut_dugumler.add(k.kaynak)
            mevcut_dugumler.add(k.hedef)

        for (e_id, cikis, dogus_ani) in injeksiyon:
            if e_id != emtia.emtia_id:
                continue
            inj_dugum = Dugum(cikis, dogus_ani)
            if inj_dugum in mevcut_dugumler:
                continue
            adaylar_zaman = sorted(
                an for an in kaynak_zamanlari_by_tm.get(cikis, set()) if an >= dogus_ani
            )
            if adaylar_zaman:
                ilgili.append(Kenar(inj_dugum, Dugum(cikis, adaylar_zaman[0]), "bekleme", None))

        emtia_kenarlari[emtia.emtia_id] = ilgili
        ust_sinir_desi = int(round(emtia_toplam_desi[emtia.emtia_id] * olcek))
        for j, kenar in enumerate(ilgili):
            f[(emtia.emtia_id, kenar)] = model.NewIntVar(
                0, ust_sinir_desi, f"f_{emtia.emtia_id}_{j}"
            )

    # --- 3) Akış korunumu + talep karşılama ---------------------------------------------
    teslim: dict[tuple[str, Dugum], cp_model.IntVar] = {}
    for emtia in emtialar:
        ilgili = emtia_kenarlari[emtia.emtia_id]
        dugumler_e: set[Dugum] = {k.kaynak for k in ilgili} | {k.hedef for k in ilgili}
        for (e_id, cikis, dogus_ani) in injeksiyon:
            if e_id == emtia.emtia_id:
                dugumler_e.add(Dugum(cikis, dogus_ani))

        # Determinizm: `set` iterasyon sırası PYTHONHASHSEED'e (string hash'i) bağlı,
        # koşudan koşuya değişebilir — kısıt/değişken oluşturma sırası CP-SAT'ın eşit-
        # maliyetli çözümler arasındaki seçimini etkileyebilir. Sıralı işle.
        for dugum in sorted(dugumler_e, key=lambda d: (d.tm, d.an)):
            icdogru = [
                f[(emtia.emtia_id, k)] for k in ilgili if k.hedef == dugum
            ]
            disdogru = [
                f[(emtia.emtia_id, k)] for k in ilgili if k.kaynak == dugum
            ]
            enjekte = int(round(
                injeksiyon.get((emtia.emtia_id, dugum.tm, dugum.an), 0.0) * olcek
            ))

            if dugum.tm == emtia.varis:
                # Varış TM'sine ulaşan akış TAMAMEN o düğümde teslim edilir — aynı
                # düğümden kısmen devam etmesine (bekleme dahil) izin VERİLMEZ.
                # Aksi halde "kısmi teslim + kısmi bekleyerek devam" belirsizliği
                # oluşur: `emtia_graf.akis_ayristir` (#19) yalnız kenar akışına bakar,
                # düğümde ne kadarının "teslim" sayıldığını bilmez — bu iki yorumu
                # ayıramayıp AkisTutarsizligi fırlatır. Varışa ulaşan yükün orada
                # beklemesi için mantıklı bir sebep de yok (zaten hedefte).
                model.Add(sum(disdogru) == 0)
                t_var = model.NewIntVar(
                    0, int(round(emtia_toplam_desi[emtia.emtia_id] * olcek)),
                    f"teslim_{emtia.emtia_id}_{dugum.tm}_{dugum.an.isoformat()}",
                )
                teslim[(emtia.emtia_id, dugum)] = t_var
                model.Add(sum(icdogru) + enjekte == t_var)
            else:
                model.Add(sum(icdogru) + enjekte == sum(disdogru))

        model.Add(
            sum(v for (e_id, _), v in teslim.items() if e_id == emtia.emtia_id)
            == int(round(emtia_toplam_desi[emtia.emtia_id] * olcek))
        )

    # --- 4) Bacak kapasitesi --------------------------------------------------------------
    kenarlar_servis = [k for k in kenarlar if k.tur == "servis"]
    for kenar in kenarlar_servis:
        akan = [f[(e.emtia_id, kenar)] for e in emtialar if (e.emtia_id, kenar) in f]
        if not akan:
            continue
        aday = kenar.servis_adayi
        model.Add(sum(akan) <= aday.kapasite_desi * olcek * x[aday])

    # --- 5) Elleçleme kapasitesi (TM-gün, gece yarısı oransal — §3) ------------------------
    # Düğüm anları (kaynak.an = yükleme BİTİŞİ/kalkış, hedef.an = boşaltma BAŞLANGICI, bkz.
    # `Servis.ziyaret_ani`) tam-kapasite varsayımıyla sabitlenmiş (§5.4 "zaman sabitlenir");
    # elleçleme penceresi de aynı varsayımla (`kapasite_desi`) geriye/ileriye açılır, işlem
    # gece yarısını aşıyorsa `f` akışı `_gun_paylari` oranıyla iki güne bölünür.
    ellecleme_gruplari: dict[tuple[str, object], list[tuple[int, cp_model.IntVar]]] = {}
    for kenar in kenarlar_servis:
        akan = [f[(e.emtia_id, kenar)] for e in emtialar if (e.emtia_id, kenar) in f]
        if not akan:
            continue
        aday = kenar.servis_adayi
        ellecleme_dk = math.ceil(aday.kapasite_desi * config.ELLECLEME_DK_PER_DESI)

        pencereler = (
            (kenar.kaynak.tm, kenar.kaynak.an - timedelta(minutes=ellecleme_dk), kenar.kaynak.an),
            (kenar.hedef.tm, kenar.hedef.an, kenar.hedef.an + timedelta(minutes=ellecleme_dk)),
        )
        for tm, pencere_baslangic, pencere_bitis in pencereler:
            for gun, oran in _gun_paylari(pencere_baslangic, pencere_bitis).items():
                katsayi = int(round(oran * _ORAN_OLCEK))
                if katsayi == 0:
                    continue
                anahtar = (tm, gun)
                ellecleme_gruplari.setdefault(anahtar, []).extend(
                    (katsayi, var) for var in akan
                )

    for (tm, gun), terimler in ellecleme_gruplari.items():
        kapasite = kisitlar.ellecleme_kapasitesi.get(tm, 0.0)
        model.Add(
            sum(katsayi * var for katsayi, var in terimler)
            <= int(round(kapasite * olcek * _ORAN_OLCEK))
        )

    # --- 6) Tır slotu (TM-gün) -------------------------------------------------------------
    tir_gruplari: dict[tuple[str, object], list[cp_model.IntVar]] = {}
    for kenar in kenarlar_servis:
        aday = kenar.servis_adayi
        if aday.servis.arac_tipi != "Tır":
            continue
        for dugum in (kenar.kaynak, kenar.hedef):
            anahtar = (dugum.tm, dugum.an.date())
            tir_gruplari.setdefault(anahtar, []).append(x[aday])
    for (tm, gun), sayaclar in tir_gruplari.items():
        kapasite = kisitlar.tir_kapasitesi.get(tm, 0)
        model.Add(sum(sayaclar) <= kapasite)

    # --- 7) Amaç fonksiyonu -----------------------------------------------------------------
    terimler = []
    for aday, var in x.items():
        if aday.zorunlu:
            continue  # sabit (x=1), amaç fonksiyonunu yönlendirmez (§5.4)
        katsayi = int(round(_sabit_kisim_tl(aday, kisitlar) * _PARA_OLCEK))
        terimler.append(katsayi * var)

    for kenar in kenarlar_servis:
        aday = kenar.servis_adayi
        katsayi = int(round(
            _degisken_katsayi_tl_per_desi(aday, kisitlar) * _PARA_OLCEK / olcek
        ))
        if katsayi == 0:
            continue
        for e in emtialar:
            if (e.emtia_id, kenar) in f:
                terimler.append(katsayi * f[(e.emtia_id, kenar)])

    for (e_id, dugum), var in teslim.items():
        katsayi = int(round(
            _ceza_katsayi_tl_per_desi(dugum, emtia_by_id[e_id].sla_bitis_ani) * _PARA_OLCEK / olcek
        ))
        if katsayi == 0:
            continue
        terimler.append(katsayi * var)

    model.Minimize(sum(terimler))

    if warm_start:
        # Zorunlu (kiralık) adaylar `x[aday]` sabittir (`NewConstant`), gerçek bir karar
        # değişkeni değildir — `AddHint`e verilirse CP-SAT hata verir. Zaten x'leri
        # sabit olduğu için hint'e ihtiyaçları da yok.
        # `AddHint` TEK (değişken, değer) çifti alır (liste değil) — her ipucu için
        # ayrı ayrı çağrılmalı.
        for aday in warm_start:
            if aday in x and not aday.zorunlu:
                model.AddHint(x[aday], warm_start[aday])

    # --- 8) Çöz --------------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = zaman_limit_sn
    solver.parameters.max_deterministic_time = zaman_limit_sn
    # BİLİNEN SINIRLAMA (canlı testle issue #21'de tespit edildi): `max_time_in_seconds`
    # duvar saati bazlıdır ve bu iş yükünde deterministic_time'dan (iş birimi bazlı,
    # gerçekten süreçler-arası sabit olan sınır) ~3-5x daha hızlı birikir — yani pratikte
    # kesmeyi HER ZAMAN duvar saati yapar. Zaman sınırına gerçekten çarpılan (OPTIMAL
    # ispatlanamayan, FEASIBLE'da kalan) "zor" pencerelerde bu, sistem yüküne göre koşudan
    # koşuya FARKLI (ama yine geçerli) bir noktada durabiliyor — config.SEED'in "bit
    # düzeyinde aynı" idealini bu dar durumda bozar. Bilinçli tercih: `max_deterministic_time`
    # tek başına kullanılsa determinizm garanti edilir ama ölçülen oranla pencere başı süre
    # ~3sn'den ~12sn'ye çıkıyor (bu branch'in öncelik verdiği hız hedefiyle çelişir) ve oran
    # donanıma göre değişeceğinden güvenilir kalibre edilemiyor. O yüzden hız korunuyor;
    # olası varyasyon zaten zararsız çünkü kayan_pencere_coz her pencerede MILP'i greedy'nin
    # GERÇEK maliyetiyle açıkça kıyaslayıp kötüyse greedy'ye düşüyor (bkz. `kayan_pencere.py`
    # `not_` alanı) — "greedy'den kötü olmama" ve kuruş kapısı garantisi buradan geliyor,
    # CP-SAT'ın koşular arası aynı FEASIBLE noktayı bulmasından değil. Etki alanı dar: yalnız
    # OPTIMAL ispatlanamayan pencerelerde, ve yalnız hangi (yine geçerli) planın seçildiğini
    # değiştirir — hiçbir zaman kabul kriterlerini (greedy'den kötü olma, kuruş kapısı) ihlal
    # etmez. `num_search_workers=1` + `random_seed` + `PYTHONHASHSEED=0` (main.py) OPTIMAL
    # ispatlanan pencerelerde ve greedy'de tam determinizmi zaten sağlıyor.
    #
    # Determinizm (proje kuralı: teslim edilen dosyalar her koşuda bit düzeyinde
    # aynı olmalı, config.SEED). CP-SAT varsayılan olarak sabit değil; paralel arama
    # da (num_search_workers>1) çekirdek sayısına göre farklı sonuç bulabileceğinden
    # tek işçiyle sabitleniyor. NOT: bunlar TEK BAŞINA yeterli değil — Python'ın string/
    # set hash'i de (PYTHONHASHSEED) süreçler arası sabitlenmeli, bkz. main.py'nin giriş
    # noktası koruması.
    solver.parameters.random_seed = config.SEED
    solver.parameters.num_search_workers = 1
    # Sıfır gap'i (kanıtlanmış tam optimal) ıspatlamak genelde arama süresinin en
    # pahalı kısmıdır — iyi bir çözümü hızlı bulur ama "daha iyisi yok" ispatına
    # kalan bütçenin çoğunu harcar. %1 içindeki bir çözüm zaten greedy'den kat kat
    # ucuz olduğu için (kayan_pencere.py kıyas+fallback'i ayrıca garanti ediyor)
    # burada durmak güvenli ve çok daha hızlı.
    solver.parameters.relative_gap_limit = config.MILP_GORECELI_GAP
    durum = solver.Solve(model)
    durum_adi = solver.StatusName(durum)
    print(f"milp_coz: {durum_adi} ({solver.WallTime():.1f} sn) — {solver.ResponseStats()}")

    if durum_adi not in ("OPTIMAL", "FEASIBLE"):
        return CozumSonucu(
            x={}, kenar_akislari={}, sabit_maliyet_tl=0.0, degisken_ellecleme_tl=0.0,
            sla_ceza_tl=0.0, toplam_maliyet_tl=0.0, durum=durum_adi,
            cozum_suresi_sn=time.perf_counter() - t0, gap=None,
        )

    # --- 9) Sonucu gerçek TL/desi birimlerine geri çevir ----------------------------------
    x_sonuc = {aday: solver.Value(var) for aday, var in x.items()}

    kenar_akislari: dict[str, dict[Kenar, float]] = {e.emtia_id: {} for e in emtialar}
    for (e_id, kenar), var in f.items():
        deger = solver.Value(var) / olcek
        if deger > 1e-9:
            kenar_akislari[e_id][kenar] = deger

    sabit_tl = sum(
        _sabit_kisim_tl(aday, kisitlar) * sayi
        for aday, sayi in x_sonuc.items() if sayi > 0
    )
    degisken_tl = sum(
        _degisken_katsayi_tl_per_desi(kenar.servis_adayi, kisitlar) * deger
        for e_akislar in kenar_akislari.values()
        for kenar, deger in e_akislar.items()
        if kenar.tur == "servis"  # bekleme kenarları (sentetik dahil) maliyet taşımaz (§3)
    )
    sla_tl = sum(
        _ceza_katsayi_tl_per_desi(dugum, emtia_by_id[e_id].sla_bitis_ani)
        * (solver.Value(var) / olcek)
        for (e_id, dugum), var in teslim.items()
    )

    ust_sinir = solver.BestObjectiveBound()
    hedef = solver.ObjectiveValue()
    gap = abs(hedef - ust_sinir) / abs(hedef) if hedef else 0.0

    return CozumSonucu(
        x=x_sonuc,
        kenar_akislari=kenar_akislari,
        sabit_maliyet_tl=round(sabit_tl, 2),
        degisken_ellecleme_tl=round(degisken_tl, 2),
        sla_ceza_tl=round(sla_tl, 2),
        toplam_maliyet_tl=round(sabit_tl + degisken_tl + sla_tl, 2),
        durum=durum_adi,
        cozum_suresi_sn=time.perf_counter() - t0,
        gap=gap,
    )
