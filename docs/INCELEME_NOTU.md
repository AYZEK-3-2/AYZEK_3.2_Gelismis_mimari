# AYZEK 3.2 — Uçtan Uca İnceleme Notu

**Kapsam:** Devir notu §11'in 1. ve 3. maddeleri — `--full` (MILP+LNS) uçtan uca
doğrulaması ve teslim provası — ve bu sırada baştan sona yapılan kod incelemesi.

**Yöntem:** Devir notu §5'teki disiplin izlendi — dosyaların tamamı okundu, her
iddia gerçek veriye karşı ölçüldü, bulunan her hata için hatayı yakalayan bir
test eklendi ve o testin **eski kodda gerçekten patladığı** ayrı bir `git
worktree`de doğrulandı.

---

## 1. Sonuç özeti

Yedi bulgu çıktı; altısı düzeltildi, biri açık bırakıldı (aşağıda §4).

| # | Bulgu | Etki | Durum |
|---|---|---|---|
| 1 | Araç, taşıdığı yük **doğmadan** kalkıyor | 182 satır (%4,1), 671.231 desi — fiziksel olarak geçersiz plan | Düzeltildi + yeni kapı |
| 2 | Araç başına **tek talep** kısıtı | 608 talep (1,32M desi, %17,8) sığmıyor → +14 gün → 186,5M TL SLA | Düzeltildi |
| 3 | Çıktı sütunları jüri şablonuyla **uyuşmuyor** | Şartname gereği **değerlendirme dışı** | Düzeltildi + yeni kapı |
| 4 | MILP model kurulumu O(düğüm × kenar × emtia) | `--full` hiç koşamıyordu (20+ dk, 1,3 GB) | Düzeltildi |
| 5 | MILP **kanıtlanmış çözümsüz** (INFEASIBLE) | `--full` bağlansa da çalışmazdı | Düzeltildi |
| 6 | Kayan pencere son penceresi yük düşürüyor | 16.211 desi / 92 talep sessizce kayboluyordu | Düzeltildi + güvence |
| 7 | Araç tipi **gerçek yük bilinmeden** seçiliyor | 137 spot araç gereksiz pahalı tiple — 1,68M TL | Düzeltildi |
| 8 | Kiralık rezervasyonu tam araç kapasitesinden — Kocaeli'yi tamamen kilitliyor | 120 satır +14 gün → 5,04M TL | Düzeltildi |
| 9 | `tir_slot_tahsis` elleçleme kapasitesini hiç görmüyor | (8) düzelince 7 TM-günde aşım | Düzeltildi |
| 10 | `_talepleri_ata` kapasiteyi görmüyor | Gerçek yük tahminden sapıyor, kapı patlıyor | Düzeltildi |
| 11 | Simülatör varış elleçlemesini **yanlış pencereye** yazıyor | Gece yarısına yakın varışlarda yanlış gün | Düzeltildi |
| 12 | Yedek araç sabit +14 gün ötelenmiş | 22 satır için 3,99M TL | Düzeltildi |
| 13 | MILP gerçek ölçekte çözülemiyor | `--full` kazanç getirmiyor (greedy'ye düşüyor) | **Açık** |
| 14 | Kayan pencerede kapasite defteri pencereler arası taşınmıyor | `--full` kapasite ihlalli plan üretiyor (kapı bloke ediyor) | **Açık** |

**Ölçülen toplam etki (gerçek veri, uçtan uca):**

```
                        ÖNCE            SONRA          fark
Araç maliyeti      57.918.428 TL   49.029.681 TL     −15,3%
SLA cezası        215.777.591 TL    1.653.691 TL     −99,2%
TOPLAM            273.696.018 TL   50.683.372 TL     −81,5%

Doğuş anı ihlali        182 satır          0
Sığmayan talep               608           0
Ufuk dışı satır              863          14
Ufuk dışı SLA      186.534.874 TL         56 TL
Toplam süre               36,0 sn     19,6 sn
```

Mimari §10 sağlık testlerinin tamamı temiz (`scripts/saglik_kontrolu.py`).

---

## 2. Düzeltilen bulgular

### 2.1 Yük doğmadan kalkan araç *(en ciddi doğruluk hatası)*

`katman2_planlama._talepleri_ata` talep kuyruğunu `(tarih, slot)` sırasına,
araçları ise **yerleştirme sırasına** göre eşleştiriyordu. `servis_bilgileri`
zaman sıralı değildir — önce 7 günün tamamının kiralıkları, sonra tır, sonra
spot eklenir — yani listenin ilerisinde daha erken kalkan araçlar bulunur. İki
sıra örtüşmediği için bir araç, kendi kalkışından **günler sonra** doğacak yükü
taşıyabiliyordu.

Gerçek veride: **182 satır (%4,1), 671.231 desi (tüm talebin %9'u)**, en uç
örnekte yük kalkıştan **5 gün 15 saat** sonra doğuyordu (V0435, 29.06 19:00'da
kalkıp 04.07 17:00 talebini taşıyor).

Bu, MVP'yi öldüren hata sınıfının aynısıdır (687 satırın 300'ü fiziksel olarak
geçersizdi) ve **hiçbir kapı yakalamıyordu**:

- `dogrula_rota_gecerliligi` yalnız durak **sırasına** bakar
- `dogrula_zaman_cakismasi` yalnız aracın **kendi bacakları** arasındaki tutarlılığa
- `_hesapla_sla` yalnız **geç** teslimi cezalandırır — erken kalkış cezasızdır

MILP yolu bu hatayı taşımıyordu (`post_pass._hazir_ani` doğuş anını
`max(dogus_ani, gun_baslangici)` ile zaten koruyor); hata yalnızca teslim edilen
greedy yolundaydı.

**Düzeltme:** eşleştirme hat bazında zaman sıralı yapılıyor — araçlar kalkışa,
talepler doğuşa göre sıralanıyor, her araç yalnız kalkışına kadar doğmuş
talepleri alıyor. Ayrıca `katman3_simulator.dogrula_dogus_ani` eklendi:
optimizatörden bağımsız, çıktı dosyası üzerinden çalışan yeni kapı.

### 2.2 Araç başına tek talep kısıtı

Her araç kuyruğun başından **tek bir ısırık** alıp duruyor, kalan kapasitesi
çöpe gidiyordu. Koddaki gerekçe şuydu:

> "Araç başına TEK talep — `dogrula_zaman_cakismasi` birden fazla satırı aynı
> araçta farklı 'bacak' sayar ve yanlış hata verir."

Bu **artık doğru değildi**: `dogrula_zaman_cakismasi` sonradan bacak bazında
tekilleştirilecek şekilde düzeltilmiş, yorum bayat kalmıştı. Kısıt gereksiz
yere duruyordu.

Ölçülen maliyeti:

- **hiçbir hatta araç eksiği yok** (289 hattın hepsinde araç ≥ talep satırı)
- 289 hattın yalnız **9'unda** kapasite açığı var
- buna rağmen **608 talep (1,32M desi, %17,8)** sığmıyor
- ve **54 araç tamamen boş** kalıyor

Sığmayanlar +14 gün ötelenip **186,5M TL** SLA cezası üretiyordu — toplam amaç
fonksiyonunun %68'i tek bir gereksiz kısıttan geliyordu.

**Yan etki (ayrıca düzeltildi):** çoklu yükte `desi` artık birden fazla dilimin
toplamı; ardışık toplama float64'te son bit'te sapma bırakıyor (12000.0 yerine
12000.000000000002). Ham `ceil(desi × 0,01)` bunu gerçek kesir sanıp süreyi bir
dakika şişiriyor ve katman2 ile katman3 toplamı farklı sırada yaptığı için
**kuruş kapısı** araç başına ±6,60 / ±10,61 TL (tam bir dakikalık kira) sapmayla
kırılıyordu. `config.TAVAN_TOLERANSI_DK` (1e-9 dk = 1e-7 desi) eklendi, iki
tarafta da ayrı ayrı uygulandı.

### 2.3 Çıktı sütunları şablonla uyuşmuyor *(diskalifiye riski)*

Teslim provasında yakalandı. `Tasima-plani.xlsx` jüri şablonundan **üç** noktada
ayrışıyordu:

| Üretilen | Şablon |
|---|---|
| `Çıkış` / `Varış` | `Çıkış Transfer Merkezi` / `Varış Transfer Merkezi` |
| `Çıkış elleçleme süresi`, `Varış elleçleme süresi` | `Varış elleçleme süresi`, `Çıkış Elleçleme süresi` |
| `Toplam maliyet`, `SLA cezası` | `SLA cezası`, `Toplam maliyet` |

Şartname: *"bu formata uymayan takımların sonuçları kesinlikle değerlendirmeye
alınmayacaktır."* Yani bu tek başına teslimi geçersiz kılabilirdi.

**Neden hiçbir test görmedi:** sütun listesi hem yazıcıya
(`plan_yazici.SABLON_SUTUNLARI`) hem simülatöre (`simulator.PLAN_SUTUNLARI`)
**elle, aynı yanlışla** yazılmıştı. Sistem kendi içinde tutarlı olduğu için tüm
kapılar geçiyordu. Format kapısı da yalnız saat biçimine ve araç tiplerine
bakıyordu.

**Düzeltme:** iki liste de şablona hizalandı ve
`format_kapisi.dogrula_sablon_sutunlari` eklendi — kontrol artık elle yazılmış
bir listeye değil, **şablon dosyanın kendisine** karşı yapılıyor. Her iki çıktı
dosyası için çalışıyor, liste bir daha sessizce sapamaz.

> Not: `Çıkış Elleçleme süresi`teki büyük **E** (varış sütununda küçük e)
> şablonun kendi tutarsızlığıdır. Bilerek birebir kopyalandı, düzeltilmedi.

### 2.4 MILP model kurulumu O(düğüm × kenar × emtia)

`--full` bugüne kadar hiç uçtan uca koşmamıştı. `main.py` yalnız
`"henuz hazir degil"` uyarısı basıp greedy'ye düşüyor, `--milp-minutes` hiçbir
yere gitmiyordu. Gerçek veriyle koşturulunca darboğaz CP-SAT'ta değil, çözücünün
süre sınırının **göremediği** Python aşamasında çıktı: akış korunumu her düğüm
için ilgili kenar listesinin tamamını iki kez tarıyordu.

| Pencere | Düğüm | Kenar | Emtia | Karşılaştırma | Kurulum |
|---|---|---|---|---|---|
| 1 gün | 3.298 | 8.002 | 68 | ~1,8 milyar | >10 dk |
| 3 gün | 9.831 | 23.973 | 136 | ~45 milyar | >20 dk (1,3 GB) |

Düğüm → gelen/giden indeksi tek geçişte kuruluyor; aynı kısıtlar O(kenar × emtia)
ile üretiliyor. **Ölçüm: 1 günlük pencere kurulumu >10 dk → ~11 sn.**

### 2.5 MILP kanıtlanmış çözümsüz (INFEASIBLE)

Kurulum düzeldikten sonra CP-SAT 1 günlük gerçek dilimi **12,5 saniyede
INFEASIBLE olarak kanıtladı** — yani yavaş değil, çözümsüz.

Kaynağı daraltıldı: elleçleme kapasitesi ×1000 **ve** tır slotu ×1000 yapılınca
bile INFEASIBLE. Yani kısıt değil, **yapı** sorunu: akış korunumu yükün ağdan
çıkmasına izin vermiyor — enjekte edilen her desi bir varış düğümüne ulaşmak
*zorunda*. Pencere yalnız kendi günlerinin servislerini gördüğü için, pik günde
(29.06) **18 TM'nin 17'si elleçleme kapasitesinin %14–52 üstündeyken** bu talep
karşılanamaz.

```
ASIM Karaman   :  66.506 > 43.830  (x1,52)
ASIM Şanlıurfa : 148.191 > 101.147 (x1,47)
ASIM Kütahya   :  94.778 > 64.732  (x1,46)
ASIM Yalova    : 666.758 > 513.171 (x1,30)
... 17 TM
```

Bu, mimarinin kendi tespitinin ("bekletme yapısal zorunluluk, kenar durum
değil") modele hiç yansımamış olması demek.

**Düzeltme:** `devir` değişkeni — yük pencerenin sonunda bulunduğu TM'de
kalabilir, `kalan_desi` defteri onu bir sonraki pencereye taşır. Ceza bir günlük
gecikmenin SLA maliyetine denk (`config.MILP_DEVIR_CEZA_TL_PER_DESI = 0,4 × 24`).
Devir yalnız her TM'nin pencere içindeki **son** düğümüne konur (her düğüme
konsaydı 1 günlük pencerede 224 bin gereksiz değişken olurdu).

### 2.6 Kayan pencerede sessiz yük kaybı

Yukarıdaki `devir` mekanizması **son** pencerede yük düşürüyordu: devredecek
pencere kalmayınca park eden yük yok oluyordu. Mevcut kayan pencere testi bunu
yakaladı (10.000 desinin 2.000'i teslim edilmiyordu). Son pencerede devir
yasaklandı.

Ayrıca `_commit_ayir`'in son penceredeki **üst gün sınırı** kaldırıldı:
`spot_placer` elleçleme taşınca bir servisi ufkun ötesine erteleyebiliyor ve
üst sınır uygulandığında o servisler hiçbir pencerede commit edilemeyip
taşıdıkları yükü düşürüyordu — gerçek veride **16.211 desi / 92 talep**.

`kayan_pencere_coz` sonuna açık bir güvence eklendi: hiçbir desi commit
edilmeden kalırsa hata fırlatılıyor. Bu güvence 16.211 desilik kaybı canlı
koşuda yakalayan şeydir.

---

## 3. Teslim provası (§11.3)

Otomatik kontrol listesi — hepsi geçiyor:

```
=== Talep-tahmini.xlsx ===          === Tasima-plani.xlsx ===
[OK] sütun adı+sırası şablonla      [OK] sütun adı+sırası şablonla
[OK] TAM 4046 satır                 [OK] Tarih GG.AA.YYYY metin
[OK] Tarih GG.AA.YYYY metin         [OK] Saat SS:DD (saniyesiz — FARKLI)
[OK] Saat SS:DD:ss metin            [OK] Araç Tipi ∈ {Spot, Kiralık}
[OK] yalnız 09:00:00 / 17:00:00     [OK] Araç türü 4 tipten
[OK] <0,5 satırlar da var           [OK] plan ID kökleri tahminde var
[OK] negatif tahmin yok             [OK] taşınacak her talep planda
[OK] Talep ID tekil

=== Muhasebe invariantı (§8.2) ===  === Desi korunumu ===
[OK] maliyet araç başına tek satır  [OK] plan taşınan == tahmin toplam
[OK] her aracın maliyeti var
[OK] SLA cezası talep başına ≤1
```

**Determinizm:** iki koşunun çıktıları **içerik olarak** birebir aynı.

> README'nin "bit düzeyinde aynı" iddiası yanlıştı ve düzeltildi: `.xlsx` bir
> zip'tir ve içinde oluşturma zaman damgası taşır, dolayısıyla md5'leri her
> koşuda farklı çıkar. Doğrulama dosyaları okuyup karşılaştırarak yapılmalı.

**Runtime:** toplam 25,2 sn (veri 0,7 · tahmin 5,8 · planlama 2,3 · doğrulama
16,4). Devir notundaki 124,8 sn ölçümünün oldukça altında.

**Testler:** 253 yeşil (~2 dk).

---

### 2.7 Araç tipi gerçek yük bilinmeden seçiliyor

Tip seçimi (`spot_placer._araç_sec`, `tir_slot_tahsis`) araç oluşturulurken, yani
o aracın gerçekte ne taşıyacağı bilinmeden yapılıyor — tam kapasite varsayımıyla
"desi başına en ucuz" tip seçiliyor. Atama bittiğinde araç çoğu zaman ondan az
taşıyor ve seçim artık optimal değil: küçük yükte saatlik kirası düşük bir araç
neredeyse her zaman daha ucuz.

Ölçüm: 3.779 spot aracın **137'si** daha ucuz bir tiple taşınabiliyordu,
fazladan maliyet **1.679.867 TL**.

**Düzeltme:** `_gercek_yukte_en_ucuz_tip` — atama bittikten sonra, gerçek yükle
en ucuz tip yeniden seçiliyor. Tır'a **yükseltme yapılmaz** (tır dokunuşu
(TM, gün) slotu tüketir ve o bütçe `tir_slot_tahsis`te zaten dağıtılmıştır);
tırdan düşürmek serbesttir, slot boşaltır. Elleçleme süresi tipe değil desiye
bağlı olduğundan TM-gün elleçleme muhasebesi etkilenmez.

Ölçülen kazanç: **1.680.038 TL** (tahminle birebir), ve "daha ucuz tiple
taşınabilecek araç" sayısı 137 → **0**.

### 2.8 Kapasite muhasebesi üç ayrı yerde, gerçek yük bilinmeden yapılıyordu

*(bulgu 8–12, ikinci inceleme turu)*

En büyük ikinci kazanç buradan geldi. Elleçleme kapasitesi `kiralik_placer`,
`tir_slot_tahsis` ve `spot_placer`'da **tahminle** düşülüyor, gerçek yük ise
`_talepleri_ata`da belirleniyordu. Zincirleme sonuçlar:

**① Kiralık rezervasyonu tam araç kapasitesindendi.** Mimaride "muhafazakâr,
bug değil" diye not edilmişti — ama gerçek veride muhafazakâr değil, yıkıcı:

```
Kocaeli   rezerv 91.200 / kapasite 89.262 = %102,2   kalan −1.938  <-- TÜKENDİ
İstanbul  rezerv 179.200 / kapasite 394.786 = %45,4
```

Kalan negatife düşünce defter 0'a kırpıyor ve spot Kocaeli'den **hiçbir gün
hiçbir şey** taşıyamıyordu. Kocaeli çıkışlı yükün tamamı 14 gün ötelenip zorla
atanıyordu: **120 satır, sadece 39.960 desi için 5.039.490 TL** SLA cezası.

**② `tir_slot_tahsis` elleçleme kapasitesini hiç hesaba katmıyordu.** ①'in aşırı
rezervasyonu bunu tesadüfen örtüyordu; ① düzeltilince kapasite kapısı 7 TM-günde
aşım yakaladı. Artık (TM, gün) bazlı bütçeyle sınırlanıyor.

> Bu kullanımı "günlerin maksimumu" olarak kalıcı düşmek denendi ve **geri
> alındı** — TM'nin bütün günlerini kısıp ①'deki kilitlenmenin aynısını
> üretiyor. Canlı testte tek bir tırın 3.000 desisi bir TM'yi 14 gün kilitledi.
> Doğru mimari: **erken katmanlar filoyu boyutlandırır, kapasiteyi gerçek yükle
> uygulayan tek yer `_talepleri_ata`dır.**

**③ `_talepleri_ata` kapasiteyi hiç görmüyordu.** Bir araç kendi gününden eski
talebi de alabildiği için bir TM-güne düşen elleçleme spot_placer'ın
varsaydığından farklı oluyordu. Artık her ısırık hem çıkış hem varış gününde
kalan kapasiteyle sınırlanıyor ve araçlar **küresel** olarak kalkış sırasına göre
işleniyor (bütçe hatlar arası paylaşılan bir kaynaktır, önce kalkan önce alır).

**④ Simülatör varış elleçlemesini yanlış pencereye yazıyordu.** `Varış Saati`
bacağın **bittiği** andır (şartname: *kullanım süresi = çıkış elleçleme + bekleme
+ seyir + varış elleçleme*). Simülatör pencereyi `[Varış Saati, Varış Saati +
elleçleme]` sayıyordu — tam bir elleçleme süresi ileri kaymış. Gece yarısına
yakın varışlarda işi yanlış güne yazıyor ve optimizatörle ayrışıyordu. Doğrusu
`[Varış Saati − elleçleme, Varış Saati]`.

**⑤ Yedek araç sabit +14 gün ötelenmişti.** SLA cezası gecikmeyle doğrusal
arttığı için bu 22 satır başına 3.988.605 TL üretiyordu. Artık kapasitesi olan
**en erken** güne gidiyor: ufuk dışı ceza 3.988.605 → **56 TL**.

Toplam etki: **83.021.581 → 50.683.372 TL (−%38,9)**, SLA cezası
34.642.195 → 1.653.691 TL (−%95).

---

## 3. Sağlık testlerinin kendisi de düzeltildi

Mimari §10 sağlık testleri `scripts/saglik_kontrolu.py` olarak koda döküldü. İki
tanesi ilk yazımda **yanlış şeyi ölçüyordu** — §10'un kendi uyarısı: *"bir
sağlık testinin yanlış olması, olmamasından beterdir."*

1. **"Pik gün SLA cezası > 0"** — cezayı `Çıkış Tarihi == pik gün` diye ölçmek
   yanlış: pik günün taşamayan yükü zaten *sonraki* günlerde kalkar, cezası da o
   satırlara düşer. Test 0,00 TL görüp şüphe veriyordu. Ölçülmesi gereken şey
   yükün **doğduğu** gün. Düzeltildikten sonra: 6.631.558 TL — mimarinin
   öngördüğü gibi.
2. **"Tır <100 km hatta çıkmıyor"** — 14 ihlal raporluyordu, hepsi **Kiralık**
   çıktı (İstanbul→Yalova 60 km, Kocaeli→Yalova 75 km). Kiralık aracın rotası ve
   türü sözleşmeyle sabittir (§3: *"rota sabit, dönüş yok, talep yetersiz olsa
   bile çıkmak zorunlu"*) — bizim seçimimiz değil, **veri**. Test yalnız SPOT
   tırlara bakacak şekilde daraltıldı.

Nihai durum: **tüm sağlık testleri temiz.**

---

## 4. Açık kalan: `--full` gerçek ölçekte çözülemiyor

`--full` artık **bağlı ve çalışıyor**: her 3 günlük pencerede model kuruluyor,
sonucu greedy'nin gerçek maliyetiyle kıyaslanıyor, ucuz olan commit ediliyor,
MILP çözemezse o pencere greedy'ye düşüyor. Bu yüzden `--full` hiçbir koşulda
greedy'den kötü bir plan üretemez.

**Ama kazanç getirmiyor:** CP-SAT ayrılan sürede hiçbir pencerede fizibil çözüm
bulamıyor, dolayısıyla tüm pencereler greedy'ye düşüyor — sonuç `--fast` ile
aynı plan, çok daha uzun sürede.

Ölçek (3 günlük pencere): **9.918 aday servis · 136 emtia · ~2,27 milyon tam
sayı `f` değişkeni**; kurulum ~61 sn, çözüm bulunamıyor.

Denenip **işe yaramayan** daraltma: emtiayı kendi çıkış TM'lerine göre kenar
filtreleme. Emtia başına ortalama **12,8 / 18** çıkış TM'si olduğu için kenarların
yalnız %12'si eleniyor — kayda değer değil.

**Asıl kaldıraç aday havuzudur**, emtia ya da kenar filtresi değil. Öneriler:

1. **Hat-gün başına aday sayısını talebe göre boyutla.** Şu an her (hat, gün,
   slot) için 4 araç tipi + 3-duraklı varyantlar üretiliyor (3 günde 9.918
   aday, hat-gün başına ~11). O hat-günün gerçek desi büyüklüğüne bakıp yalnız
   makul 1–2 araç tipini üretmek havuzu birkaç kat küçültür.
2. **3-duraklı adayları yalnız gerektiği yerde üret.** Konsolidasyonun asıl
   değeri tır slotu kıt olan TM'lerde; her hatta üretmek gereksiz.
3. **Pencereyi 1 güne indir** (3.306 aday, 68 emtia, ~340 bin değişken). Tek
   başına yetmiyor ama 1 ve 2 ile birleşince anlamlı.

### 4.1 İkinci engel: pencereler arası kapasite defteri

Canlı `--full` koşusu (9,2 dk) kapasite kapısına takıldı ve — doğru şekilde —
**hiçbir dosya yazmadı**:

```
Elleçleme aşımı: Bilecik 29.06.2026 -> 180.881 / 164.023 desi
Elleçleme aşımı: Kütahya 29.06.2026 ->  80.453 /  64.732 desi
Tır slot aşımı : Yalova  02.07.2026 ->       5 /       4 slot
Tır slot aşımı : Tekirdağ 03.07.2026 ->      3 /       2 slot
  ... (8 elleçleme + 4 tır slot ihlali)
```

Sebep: `_greedy_tam_plan` her pencerede kiralık→tır→spot zincirini **sıfırdan,
tamamen dolu bir `KapasiteDefteri` ile** çalıştırıyor. Pencere N'de commit
edilen servislerin tükettiği TM-gün elleçleme ve tır slotu, pencere N+1'in
greedy'sine hiç aktarılmıyor; commit edilen planlar toplamda kapasiteyi aşıyor.

Modül docstring'i bu riski "kapasite defterlerinin pencereler arası
sızdırılmaması" olarak not etmiş, ama etki tam tersi yönde: sızmama değil,
**hiç aktarılmama** sorunu var.

Düzeltmek için `_greedy_tam_plan`in önceden tüketilmiş kapasite durumunu girdi
olarak alması gerekiyor. Bu yapılmadı: MILP zaten hiçbir pencerede kazanmadığı
için `--full`ün çıktısı en iyi ihtimalle `--fast` ile aynı plan olurdu — teslim
açısından sıfır kazanç, geç aşamada yeni hata riski ise gerçek.

Bu iş bitene kadar **teslim için varsayılan (greedy) mod kullanılmalıdır.**
`--full` şu an bir plan üretemez (kapı bloke eder), ama geçersiz bir şey de
teslim ettirmez.

---

## 5. Bu incelemede öğrenilenler (metodolojiye ek)

Devir notu §5'teki listeye eklenecek üç madde:

1. **"Sistem kendi içinde tutarlı" ≠ doğru.** Çıktı sütunları hem yazıcıya hem
   simülatöre aynı yanlışla elle yazılmıştı; iki bağımsız katman aynı hatayı
   paylaşınca kuruş kapısı bile göremez. Dış sözleşmeler (şablon dosyası)
   **kaynağın kendisine** karşı doğrulanmalı, kopyasına karşı değil.
2. **Süre sınırı olan çözücülerde asıl darboğaz kurulum olabilir.** CP-SAT'ın
   `max_time_in_seconds`'ı yalnız *çözme* aşamasını kesiyor; model kurulumu
   Python'da ve sınırsızdır. "MILP yavaş" teşhisi 20 dakikanın CP-SAT'a hiç
   girmediğini gizliyordu.
3. **Bir kısıtın gerekçesi, gerekçenin kendisi düzeltildikten sonra da kodda
   kalır.** "Araç başına tek talep" kısıtının sebebi aylar önce giderilmişti;
   yorumu okuyup doğrulamadan güvenmek 186,5M TL'ye mal oluyordu. Yorumda
   *"çünkü X"* yazıyorsa X'in hâlâ doğru olduğu ölçülmeli.

---

## 6. Ölçüm betikleri

İncelemede kullanılan ölçümler tekrarlanabilir olsun diye
`scripts/teslim_provasi.py` altında toplandı:

```bash
python main.py --output-dir cikti/
python scripts/teslim_provasi.py cikti/    # sablon + sartname + invariant kontrolu
```
