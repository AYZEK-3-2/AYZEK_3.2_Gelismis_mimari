# AYZEK 3.2 — Proje Devir Notu

**Amaç:** Yeni bir sohbete/oturuma geçerken tüm bağlamı tek dosyadan devretmek.
Bu doküman "ne yaptık, neden yaptık, neye dikkat edilmeli"yi anlatır.

**Son güncelleme:** 22 Temmuz 2026 · main `b32a36b` · **246 test yeşil (7 dk 11 sn)**

---

## 0. Hızlı başlangıç (yeni oturum buradan okusun)

| | |
|---|---|
| **Repo (yerel)** | `C:\Users\pcc\Desktop\AYZEK 3.2\AYZEK_3.2_Gelismis_mimari` |
| **GitHub** | `AYZEK-3-2/AYZEK_3.2_Gelismis_mimari` (private) |
| **Pano** | org Projects #2 — "AYZEK Gelişmiş Aşama" |
| **Mimari (tek kaynak)** | `docs/GELISMIS_Sistem_Mimarisi_v4.md` (+ .docx) |
| **Şartname/soru-cevap** | `veri/dokuman/sartname_gelismis.pdf`, `soru_cevap_oturumu_oncesi.pdf` |
| **Durum** | 22 issue'nun **tamamı kapalı**, açık branch yok, sistem uçtan uca çalışıyor |
| **NOT** | Eski MVP repo'su (`AYZEK-3.2-PROJECT`) ayrı ve **artık geçersiz** — gelişmiş aşama bu repodur |

```bash
pip install -r requirements.txt
pytest                    # 246 test
python main.py            # cikti/Tasima-plani.xlsx + cikti/Talep-tahmini.xlsx
```

---

## 1. Yarışma kuralları — bağlayıcı kısıtlar

Bunlar şartname + jüri soru-cevabından **doğrudan** alınmıştır. Varsayım değildir;
kod bunlara birebir uymak zorundadır. Detay: mimari §3.

### 1.1 Zaman ve maliyet
- **Zaman çözünürlüğü dakika.** Araç günün her dakikasında çıkabilir.
- **Süreler yukarı tam sayıya yuvarlanır:** seyir `⌈saat × 60⌉` dk (0,92 h → **56 dk**), elleçleme `⌈desi × 0,01⌉` dk.
- **Kullanım süresi = çıkış elleçleme + bekleme + seyir + varış elleçleme.**
  Jüri örneği: 10.000 desi + 5 saat yol = **500 dk**; +1 saat bekleme = **560 dk**.
- Maliyet = saatlik kira × kullanım süresi + km × km maliyeti.
- **Araç beklemesi ücretli, yük beklemesi bedava** (yük TM'de beklerken araç serbest bırakılır).

### 1.2 SLA
- Başlangıç: **orijinal çıkış TM'sindeki talep tamamlanma anı** (09:00 / 17:00).
- Bitiş: **orijinal varış TM'sinde elleçlemenin bitiş anı** (araç varış anı değil).
- 1 gün = tam 24 saat, 2 gün = 48 saat.
- Ceza = geciken desi × `⌈gecikme saati⌉` × **0,4 TL**. 1 dk gecikme = 1 saat ceza.
- SLA **sert kısıt değil**, amaç fonksiyonunda ceza terimi — bekletmek bazen optimaldir.

### 1.3 Kapasiteler
- **Elleçleme kapasitesi** TM başına **günlük**, 00:00'da sıfırlanır. Çıkış + varış elleçlemelerinin **toplamını** kapsar.
- **Konsolidasyon:** `x` indirip `y` yüklersen kapasiteden **x+y** düşer.
- **Gün-aşırı sefer:** elleçleme **yapıldığı TM'de yapıldığı gün** kotadan düşer (çıkış 29.06 İstanbul'dan, varış 30.06 Tekirdağ'dan).
- **Gece yarısı geçişi:** tek bir elleçleme gece yarısını aşarsa **oransal** bölünür (23:30'da 10.000 desi → o gün 3.000, ertesi gün 7.000).
- **Tır slotu** TM başına **günlük**; her dokunuşta tükenir (giden/gelen ayrımı yok). Yalnız "Tır" tipini kapsar; diğer araçlarda sayı kısıtı **yok**. Kiralık tırlar da tüketir.
- "Aynı araç = 1 slot" kuralı yalnız **araç hareket etmeden boşaltılıp tekrar yüklenirse** geçerli.
- **Kuyruk yok:** kapasiteye uygun olarak aynı anda yükleme/boşaltma yapılabilir.
- **Elleçleme atomikliği:** bir araçtaki tüm gönderiler aynı anda elleçlenir; desi bölünüp bir kısmı erken elleçlenmiş sayılamaz.

### 1.4 Araçlar
- **Kiralık:** uğrama yasak, rota sabit, dönüş yok, **talep yetersiz olsa bile çıkmak zorunlu**. Çıkış saatini biz seçeriz (o gün içinde). Konsolidasyon serbest (varışta indirip başka araca aktarma).
- **Spot:** sınırsız sefer, milk-run serbest, bir araca farklı varışlara giden yükler yüklenebilir. **Boş spot araç döndürülmez.**
- **%10 minimum doluluk kuralı KALDIRILDI** (MVP'de vardı, bu aşamada yok).

### 1.5 Çıktı formatı — format hatası = diskalifiye
> Şartname: *"bu formata uymayan takımların sonuçları kesinlikle değerlendirmeye alınmayacaktır."*

**`Talep-tahmini.xlsx`** (6 sütun):
- `Talep ID`, `Tarih`, `Talep Tamamlama Saati`, `Çıkış Transfer Merkezi`, `Varış Transfer Merkezi`, `Tahmin Edilen Desi`
- Tarih **`GG.AA.YYYY`** metin · Saat **`SS:DD:ss`** metin (`09:00:00`)
- **09:00 ve 17:00 AYRI satırlarda** · **TAM 4.046 satır** (289 hat × 7 gün × 2 slot)
- **Düşük değerli (<0,5) satırlar bile SUNULMALI** — filtrelenemez

**`Tasima-plani.xlsx`** (16 sütun):
- Satır birimi **(Araç ID, bacak, Talep ID)** — bir bacakta n talep varsa n satır
- Tarih **`GG.AA.YYYY`** · Saat **`SS:DD`** (tahmin dosyasından **farklı**, saniyesiz)
- `Araç Tipi` ∈ {Spot, Kiralık} · `Araç türü` ∈ {Tır, Kamyon, Hafif Kamyon, Kamyonet}
- **Muhasebe invariantı:** her sayısal büyüklük **sahibinin tam bir satırında**, diğerlerinde 0
  (Toplam maliyet → aracın ilk satırı; SLA cezası → talebin teslim bacağı; süreler → bacağın ilk satırı)
- Talep bölme: `D00001-1`, ikinci bölmede `D00001-1-1`
- **İki dosyanın ID'leri birebir eşleşmeli** (bölünmüş parçanın kökü tahmin dosyasında olmalı)

### 1.6 Tahmin ve puanlama
- Ufuk: **29.06.2026 09:00 – 05.07.2026 17:00**.
- **Geçmişte hiç görülmemiş TM çifti için tahmin üretilmez** (289 aktif hat; Kocaeli-varış yok).
- Teslim penceresi serbest: 5 Temmuz talebi 7 Temmuz'da teslim edilebilir (SLA cezası ödenerek).
- **Optimizasyon KENDİ tahminimiz üzerinden** değerlendirilir; tahmin ayrıca gerçekle kıyaslanır.
  → Tahmini bilerek kaydırmak (kuantil vs.) işe yaramaz; **saf doğruluk** kovalanır.
- **Runtime** = tahmin + planlama toplamı. Şartnamedeki 10 dk örnekmiş, nihai sınır sonra açıklanacak.
- Teslim: **kaynak kod + iki xlsx**. Repo klonlanıp tek komutla çalışmalı, deterministik olmalı.

### 1.7 Ölçülmüş veri gerçekleri
- 66.024 talep · 289 hat · 18 TM · 01.01–28.06.2026 (179 gün)
- Günlük desi: ort. 814.319 · **pik 2.637.199** · Pazartesi ~1,7M ↔ Pazar ~70-80k (**~20× salınım**)
- Desinin **%91'i 17:00** slotunda (09:00 ort. 513 desi, gürültülü)
- Trend: Ocak 556k/gün → Haziran 975k/gün (**%75 artış**)
- Toplam tır slotu **69**; kiralık 10 tır × 2 dokunuş = 20 → spot tıra **49**
- Tır kapasitesi **0 olan 7 TM**: Kütahya, Isparta, Bilecik, Zonguldak, Karaman, Sivas, Denizli
- Kiralık: **12 hat / toplam 14 araç** (10 tır + 4 kamyon) → 7 gün × 14 = **98 zorunlu servis**
- **Pik gün elleçleme:** plan haftası Pazartesi başlıyor; 22.06 proxy'sinde **18 TM'nin 16'sı** kapasite üstünde → bekletme/gün-yayma **yapısal zorunluluk**, kenar durum değil

---

## 2. Mimari — taşıyıcı kararlar

Kaynak: `docs/GELISMIS_Sistem_Mimarisi_v4.md`. Dört katman:

```
Katman 0  Veri & kısıt çekirdeği     immutable, doğrulanmış, tek kaynak
Katman 1  Talep tahmini               LightGBM, WAPE, 4046 satır
Katman 2  Planlama                    greedy (kiralık→tır slot→spot) + MILP/LNS
Katman 3  BAĞIMSIZ simülatör          kalite + format kapısı
```

**Neden böyle — MVP dersi:** MVP'de teslim edilen planın 687 satırının 300'ü fiziksel olarak
geçersizdi (araç uğramadığı şehre "teslim etmiş" sayıldı, 1,17M desi). İki kök neden:
(1) rota birinci sınıf nesne değildi, (2) **optimizatör kendi kendini puanlıyordu**.

Bu yüzden iki kural tartışmaya kapalı:
1. **Servis birinci sınıf nesnedir.** Talep, ancak `duraklar` içinde çıkışı varıştan **önce**
   içeren servise bağlanabilir — ihlalde exception, sessiz geçiş yok.
2. **Katman 3, Katman 2 ile hiçbir kod paylaşmaz.** Maliyet formülü dahil her şey ikinci kez
   yazılır; simülatör yalnız çıktı dosyasını okur. Kod paylaşımı ortak hatayı görünmez yapar.
   **Kuruş kapısı:** simülatör ≠ optimizatör maliyeti → teslim bloke.

---

## 3. Dosya haritası

| Modül | İş | Issue |
|---|---|---|
| `config.py` | Yalnız şartname sabitleri (0.01 dk/desi, 0.4 TL, saatler, ID formatı, ufuk, seed, MILP/LNS parametreleri) | #1 |
| `katman0_veri/yukleyici.py` | 6 excel okuma + yapısal doğrulama; calamine engine (10,9→1,2 sn) | #2 |
| `katman0_veri/kisitlar.py` | Frozen `Kisitlar` + salt-okunur sözlükler | #2 |
| `katman1_tahmin/panel.py` | Yoğun panel (103.462 satır) + sızıntısız feature'lar + tahmin ufku paneli | #8, #11 |
| `katman1_tahmin/bolme.py` | Walk-forward bölme (**bitişik**, gerçek horizon) | #8 |
| `katman1_tahmin/metrik.py` | WAPE | #9 |
| `katman1_tahmin/model.py` | LightGBM (tek global, L1, 3 seed), backtest, `tahmin_uret` | #9, #11 |
| `katman1_tahmin/yazici.py` | Talep ID üretimi + `Talep-tahmini.xlsx` | #11 |
| `katman2_planlama/servis.py` | `Servis` nesnesi + maliyet + SLA cezası (C ve D ortak çekirdek) | #12 |
| `katman2_planlama/kiralik_placer.py` | 98 zorunlu kiralık servis | #13 |
| `katman2_planlama/tir_slot_tahsis.py` | Tasarruf sıralı greedy tır slot tahsisi (**(TM,gün) bazlı**) | #14 |
| `katman2_planlama/spot_placer.py` | Kalan yük ataması + elleçleme ötelemesi | #15 |
| `katman2_planlama/plan_yazici.py` | `Tasima-plani.xlsx` + muhasebe invariantı | #16 |
| `katman2_planlama/servis_havuzu.py` | MILP aday havuzu (23.142 aday / 0,2 sn) | #18 |
| `katman2_planlama/emtia_graf.py` | Emtia toplulaştırma (4046→272) + zaman-genişletilmiş graf + akış ayrıştırma | #19 |
| `katman2_planlama/milp_cozucu.py` | CP-SAT set-partitioning | #20 |
| `katman2_planlama/kayan_pencere.py` | 3 günlük kayan pencere + warm start + post-pass | #21 |
| `katman2_planlama/lns.py` | Yık-onar iyileştirme | #22 |
| `katman3_simulator/hesaplamalar.py` | Altın vektör hesapları (süre, gece yarısı, SLA, maliyet) | #3 |
| `katman3_simulator/simulator.py` | Plan okuma, rota/çakışma/kiralık doğrulama, **bağımsız maliyet+SLA kapısı** | #4-#6 |
| `katman3_simulator/kapasite.py` | TM-gün elleçleme + tır dokunuş defteri | #5 |
| `katman3_simulator/format_kapisi.py` | Şablon uyumu, muhasebe invariantı, talep bütünlüğü | #7 |
| `main.py` | Uçtan uca akış, determinizm, süre logu, kapı başarısızlığında dosya yazmama | #17 |
| `scripts/backtest.py` | Tahmin backtest raporu | #9 |
| `scripts/slot_deney.py` | Slot mimarisi + log dönüşümü deneyi | #10 |

---

## 4. Issue issue ne yapıldı

**#1 Proje iskeleti** — klasör yapısı (`katman0_veri`…`katman3_simulator`, `tests`, `cikti`),
`requirements.txt`, `main.py` akış iskeleti, `config.py` şartname sabitleri, Windows venv README.

**#2 Katman 0** — 6 excel okuyucu + yükleme-anı doğrulama (sütun sözleşmesi, 6 dosya arası TM
tutarlılığı, talep/kiralık hatların matriste varlığı, talep_id tekilliği, panel anahtarı
tekilliği, boş/negatif, self-loop). Frozen `Kisitlar` + `MappingProxyType`.
**Karar:** sanity sayıları (69 slot, 7 sıfır-TM) loader'a **gömülmedi**, teste kondu — veri
değişirse loader çalışmaya devam eder, test uyarır. **Optimizasyon:** calamine engine → 10,9→1,2 sn.

**#3 Test altyapısı + altın vektörler** — jürinin somut örnekleri test vektörü yapıldı:
500 dk / 560 dk kullanım süresi, 23:30'da 10.000 desi → 3.000/7.000 oransal bölme,
1 dk gecikme → 1 saat ceza, 140 dk → 3 saat, 0,92 h → 56 dk. CI workflow.

**#4-#7 Simülatör** — plan okuyucu, araç zaman çizelgesi + çakışma, **rota geçerliliği**
(MVP'yi öldüren kontrol), araç tür/tip tutarlılığı, kiralık kontrolü; TM-gün elleçleme +
tır dokunuş muhasebesi (gün-aşırı atıf + gece yarısı oransal); **bağımsız maliyet ve SLA
hesabı + kuruş kapısı**; format kapısı (şablon uyumu, muhasebe invariantı, talep bütünlüğü).

**#8 Panel + feature** — yoğun panel 289×179×2 = **103.462 satır**, talep olmayan kombinasyon
**0 desi** (ham veri yalnız %63,8 dolu; sıfırlar atlanırsa model sistematik yüksek tahmin eder).
Feature'lar: haftanın günü, gün indeksi, slot, slot×gün, hat kimliği, lag 7/14/28, rolling 7/28.
**Kritik:** hedefe bağlı tüm feature'lar **≥ 7 gün (ufuk) geriden** başlar — bu sızıntı korumasının
asıl kaynağıdır. Walk-forward **bitişik** (boşluksuz): gerçek görev origin'den 1–7 gün ileriyi
tahmin etmek; v3'ün "7 gün boşluk" kuralı backtest'i h=8–14'e kaydırıyordu, **düzeltildi** (mimari §7 güncellendi).

**#9 Model + backtest** — tek global LightGBM (hat başına model YOK), L1 hedef (WAPE ile hizalı),
3 seed ensemble, deterministik. Naif taban çizgisi = geçen haftanın aynı günü+slotu (lag_7).
**Sonuç:** kat 0 (Haziran sonu) model **0,3139** < naif **0,3387** → kabul kriteri sağlandı.
17:00 slotu (hacmin %91'i) WAPE **0,2663**; 09:00 0,6636 (gürültülü, hacmin %9'u).

**#10 Slot + log deneyi** — üç varyant aynı protokolle: **D1 tek+ham 1,2106** (kazanan) <
D3 log1p 1,2463 < D2 slot-ayrı 1,2782 (naif 1,2672). Kazanan zaten mevcut config → kod değişmedi.

**#11 Tahmin çıktısı** — `tahmin_paneli_kur` (geçmiş+ufuk tek panel), `tahmin_uret` (4046 satır,
zero-floor), deterministik talep ID (`(tarih, slot, çıkış, varış)` sırası), şablon formatında yazıcı.
**ID tek kaynak:** `talep_id` kolonu varsa yazıcı onu korur (yeniden atamaz) → planlayıcıyla
uyuşmazlık yapısal olarak imkânsız. ID'ler **D70001**'den başlar (geçmiş verideki D66024 ile çakışmasın).

**#12 Servis çekirdeği** — frozen `Servis`, `talep_bagla` sıra zorlaması, izole maliyet fonksiyonu,
kanonik yuvarlamalar, `ziyaret_ani`.

**#13 Kiralık yerleştirici** — 98 zorunlu servis, çıkış saati seçimi, min(talep, kapasite),
kalanı spot'a devir, slot/elleçleme rezervasyonu. Slot dağılımı doğrulandı: Balıkesir 0,
Tekirdağ 0, İstanbul 2, Yalova 1, Kocaeli 9, Mersin 11.

**#14 Tır slot tahsisi** — tasarruf/desi (TAM formülle, elleçleme dahil) hesapla, negatifleri ele,
büyükten küçüğe greedy ata; **(TM, gün) bazlı bütçe**; <100 km hatlarda tır yok.

**#15 Spot atama + öteleme** — kalan yükü tırsız araçlara böl, TM-gün kapasite aşımında ötele.

**#16 Plan yazıcısı** — 16 sütun, muhasebe invariantı, `V0001` ID'leri.

**#17 main.py** — uçtan uca akış, `--fast/--full/--seed/--output-dir/--milp-minutes`,
aşama süre logu, **kapı geçmeden dosya yazmama** (geçici klasör), `PYTHONHASHSEED=0` ile
determinizm (CP-SAT'ın dolaylı hash bağımlılığı canlı testle bulundu).

**#18 Servis havuzu** — tır yalnız direkt, küçük araçlar ≤3 durak, sapma ≤1,3×, sıfır-tır TM
elenmesi, baskınlık budaması. **23.142 aday / 0,2 sn** (hedef <30k).

**#19 Emtia + graf** — (varış, SLA bitişi) toplulaştırma **4046 → 272 emtia**; olay-güdümlü
zaman-genişletilmiş graf; flow decomposition ile talep ID'lerine geri dağıtım (`AkisTutarsizligi`).

**#20-#22 MILP/LNS** — CP-SAT set-partitioning, 3 günlük kayan pencere + warm start + post-pass,
LNS yık-onar. **Not:** `--full` README'ye göre henüz üretim-hazır değil; varsayılan akış greedy.

---

## 5. İnceleme metodolojimiz (bu projede işe yarayan)

Bu bölüm, PR incelemelerinde **gerçekten bug bulan** yaklaşımı anlatır. Yeni oturum aynı
disiplini sürdürmeli.

1. **Dosyanın tamamını oku, grep'le yetinme.** Bulunan bug'ların çoğu (SLA parse, çok bacaklı
   maliyet, 1×/2× tutarsızlık) ancak tam okumayla görüldü.
2. **Gerçek veriye karşı çalıştır.** Mock testler yeşilken gerçek veride patlayan durumlar çıktı
   (kiralık 84 vs **98** servis; tır slotunun günlük olması).
3. **Testin doğru şeyi test ettiğini doğrula.** `test_hayalet_rota_hata` adı "hata" diyordu ama
   geçerli rota kurup hata beklemiyordu. `test_kabul_toplam_sinirli` **bug'ın kendisini** kodlamıştı.
   → *Yeşil test, doğru test demek değildir.*
4. **Kabul kriterlerini tek tek ölç.** "23.142 aday < 30.000", "0,2 sn < 30 sn", "4046 satır",
   "her aktif hat kapsanmış" — iddia değil, ölçüm.
5. **Sessiz hata kalıplarını ara:**
   - `except: continue` (SLA parse hatası her satırı sessizce atlıyordu)
   - satır sırasına bağımlılık (rota kontrolü)
   - string tarih kıyası (`"28.06.2026" > "05.07.2026"` — kronolojik değil)
   - birim/konvansiyon tutarsızlığı (graf 1× vs havuz 2× elleçleme)
   - eksik boyut (tır slotu günlük ama sayaç yalnız TM bazlı)
   - eksik bağımlılık (scikit-learn requirements'ta yok → sadece temiz kurulumda patlar)
   - sessiz filtre (`desi >= 1` → 886 satır düşüyordu)
6. **İki modül aynı şeyi farklı mı hesaplıyor?** Kuruş kapısı için ölümcül: yuvarlama,
   `int()` kesmesi, ara durak elleçlemesi.
7. **Branch testlerini izole koş** (`git worktree`), ve **merge'i lokalde dene**
   (`git merge --no-commit`) — CI kırmızısı bazen bayattır.
8. **Bug bulunca: düzelt + bug'ı yakalayan test ekle.** Testsiz düzeltme geri gelir.
9. **Commit disiplini:** Türkçe, ne+neden+nasıl doğrulandı; **Claude co-author trailer'ı YOK**.

---

## 6. Bulunan ve düzeltilen bug'lar (tekrar etmesin)

| # | Bug | Etki | Nasıl bulundu |
|---|---|---|---|
| 1 | `rolling_ort` `shift(1)` kullanıyordu | Direct multi-step'te tahmin haftasının kendi geleceğine bakıyordu (**sızıntı**) | Model kurarken feature semantiği sorgulandı |
| 2 | `ziyaret_ani` ara durak elleçlemesini atlıyordu | 3 duraklı rotada varış **erken**, SLA yanlış | PR incelemesi, çok duraklı senaryo izlendi |
| 3 | Kiralık `cikis_ani` toplam yükü kullanıyordu | adet=2 hatlarda çıkış **~3,7 saat geç**; maliyetle çelişki | Kod okuma (maliyet araç başına, süre toplam) |
| 4 | Graf ara durakta 1× elleçleme (havuz 2×) | 3-duraklı varış anı iyimser → infizibl akış kabul edilebilir | İki modülün konvansiyonu karşılaştırıldı |
| 5 | Tır slot bütçesi yalnız TM bazlı (gün yok) | Haftalık tahsis **~7× eksik** | Gerçek veri semantiği (slot günlük sıfırlanır) |
| 6 | `scikit-learn` requirements'ta yoktu | **Teslim-kritik**: jüri klonunda tahmin çöker | CI pull_request kırmızısı incelendi |
| 7 | Kalite kapısı hiç test edilmiyordu | Kapı bozuksa fark edilmezdi | Test kapsamı grep'lendi (`simulasyonu_calistir` çağrısı yok) |
| 8 | Yazıcıda `desi >= 1` filtresi | **4046 → 3160 satır** sessizce düşüyordu = format ihlali | #22 canlı testi (ekip) |
| 9 | `int()` desi kesmesi | Kuruş kapısını kırıyordu | #21 canlı testi (ekip) |
| 10 | `PYTHONHASHSEED` salınımı | CP-SAT çözümü koşudan koşuya değişiyordu (determinizm ihlali) | #21 canlı testi (ekip) |

---

## 7. Elenen alternatifler — tekrar denemeyin

Ölçüldü, kaybetti (`scripts/slot_deney.py` ile tekrarlanabilir):

| Deney | Sonuç | Neden |
|---|---|---|
| **log1p hedef** | ort 1,2463 (D1: 1,2106); Haziran'da 0,406 vs 0,275 | WAPE hacme ağırlıklı; log büyükleri sıkıştırıp modeli önemli günlerden uzaklaştırıyor |
| **Slot başına ayrı model** | ort 1,2782 | 09:00 tek başına yeterli sinyal taşımıyor; 17:00 ile paylaştığı yapıyı kaybediyor |
| **Yakınlık ağırlığı (recency)** | Haziran 0,373 vs 0,278 | Eski veri mevsimsel/hat yapısı için gerekli örnek |
| **7 gün backtest boşluğu** | Gerçek görevden farklı horizon ölçüyordu | Sızıntıyı boşluk değil, lag ≥ ufuk önlüyor |

---

## 8. Bilinen sınırlar / açık riskler

- **`--full` (MILP+LNS) üretim-hazır değil.** README: "henuz hazir degil, greedy calisir".
  Varsayılan akış greedy; MILP kalite kazancı henüz uçtan uca doğrulanmadı.
- **`gun_index` ekstrapolasyonu:** LightGBM ağaç tabanlı, eğitim aralığı ötesine genelleyemez;
  tahmin haftasında trendi sürdürmez, son seviyeyi tahmin eder. Trendi lag/rolling taşıyor.
- **Kiralık elleçleme rezervasyonu tam kapasiteden** yapılıyor (gerçek yükten değil) —
  muhafazakâr, bug değil; spot'a bıraktığı kapasite gerçekte olduğundan az.
- **`_tasarruf_per_desi` tam tır kapasitesi** varsayıyor (gerçek artık yük değil) — hassasiyet meselesi.
- **Pik gün (Pazartesi 29.06)** elleçleme yapısal olarak taşar → bir miktar SLA cezası beklenir.
  *Sağlık testi:* Pazartesi planında hiç SLA cezası yoksa muhasebe şüphelidir.
- **Runtime:** README ölçümü ~125 sn (veri 0,8 · tahmin 19,8 · planlama 6,8 · doğrulama 97,5).
  Nihai jüri sınırı belirsiz; doğrulama en pahalı aşama.

---

## 9. Çalıştırma ve komutlar

```bash
pytest                                  # 246 test (~7 dk; MILP/LNS testleri yavaş)
pytest tests/test_katman0.py -q         # tek dosya

python main.py                          # greedy, cikti/ altına iki xlsx
python main.py --seed 123 --output-dir sonuclar/
python main.py --full --milp-minutes 5  # MILP+LNS (hazır değil)

python scripts/backtest.py              # tahmin backtest raporu (WAPE, naif kıyas)
python scripts/slot_deney.py            # #10 deney tablosu (~2,5 dk)
python scripts/md_to_docx.py docs/GELISMIS_Sistem_Mimarisi_v4.md
```

**Sağlık kontrolleri (mimari §10):** tır <100 km hatta çıkıyorsa şüphe · tır çok duraklı rota
yapıyorsa slot muhasebesi şüphesi · TM-gün tır dokunuşu kapasiteyi aşıyorsa kısıt sızıntısı ·
konsolidasyon %0 ise model çalışmıyor ya da elleçleme cezası yanlış · Pazartesi SLA cezası
sıfırsa kapasite muhasebesi şüpheli.

---

## 10. Çalışma kuralları (ekip)

- **Commit:** Türkçe, açıklayıcı; ne + neden + nasıl doğrulandı. **Claude co-author trailer'ı eklenmez.**
- **Akış:** issue → branch (`<no>-<baslik>`) → PR → main. Şu an tüm branch'ler merge edilmiş durumda.
- **CI:** `.github/workflows/ci.yml`, push + pull_request. `pull_request` CI branch'i **main'le
  birleştirip** test eder — base değişince eski kırmızı **bayat** olabilir; merge öncesi lokalde
  `git merge --no-commit` ile doğrula.
- **Ekip:** Mobcik/Süleyman (tahmin + inceleme), eness2606, Emrullah0642, Hacer-Serbest, Fqtih77.
- **Token notu:** kullanılan GitHub token'ında PR/Actions okuma izni yok (issue + contents +
  projects var). PR açma/CI logu için UI kullanılıyor.

---

## 11. Sıradaki mantıklı işler

1. **`--full` (MILP+LNS) uçtan uca doğrulama** — greedy'yi gerçekten yeniyor mu, kuruş kapısından
   geçiyor mu, runtime kabul edilebilir mi. Kıyas: `main.py --fast` vs `--full` toplam maliyet.
2. **Runtime bütçesi** — doğrulama 97,5 sn ile en pahalı aşama; jüri sınırı açıklanınca optimize edilmeli.
3. **Teslim provası** — temiz klon + `pip install -r requirements.txt` + `python main.py`, iki
   dosyayı şablonlarla karşılaştır, determinizm için iki kez koş ve dosyaları diff'le.
