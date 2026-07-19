# AYZEK — Gelişmiş Çözüm Aşaması Sistem Mimarisi v4

**TEKNOFEST 2026 · Hepsiburada Lojistik Optimizasyonu**

> **v1 → v2:** v1, soru-cevap belgesi okunmadan yazıldı ve üç taşıyıcı iddiası yanlıştı: araç zincirleme ile tır slotu tasarrufu (§4.1), maliyet-farkında kuantil tahmini (§7), ve "bekleme kullanım süresine dahil değil" varsayımı. Üçü de jüri cevaplarıyla çürüdü. v2 bu cevaplar üzerine kurulmuştur; kural kaynağı olarak `sartname` + `Soru Cevap Oturumu Öncesi Gelen Sorular` esas alınmıştır.
>
> **v2 → v3:** v2 çıktı şemasını hiç ele almıyordu ve format riskini yanlışlıkla "düşük" işaretliyordu; greedy taban çizgisi (sigorta planı) tanımsızdı; test stratejisi yoktu. v3 bunları kapatır ve §5'te muhasebe invariantını tanımlar. Şablon incelemesiyle çözülen maddeler artık açık soru değildir.
>
> **v3 → v4:** Veri incelemesi üç düzeltme getirdi. (1) **Pik gün elleçleme kısıtı yapısaldır:** plan haftası Pazartesi başlıyor ve Pazartesi yükünde aynı-gün varsayımıyla 18 TM'nin 16'sı kapasite üstünde — §4.2, §4.3 ve risk matrisi düzeltildi; bekletme/gün-yayma modelin merkezine alındı. (2) §5.4'e **yük-bağımlı elleçleme süresi** çözümü eklendi (sabit-yük varsayımı + post-pass) — v3 bu bağı ele almıyordu ve §6 kapısını yapısal olarak patlatırdı. (3) v3'ün "zincirleme slot kazandırmaz" iddiası fazla keskindi: hareket etmeden boşalt+yükle = 1 dokunuş kuralı, ara TM'ye zaten hizmet gereken durumda zincirlemeye gerçek slot kazancı verir (§4.1); tır-direkt kuralı SLA gerekçesiyle korunur, zincirleme LNS fırsatı olarak işaretlendi (§5.5). İş bölümü sabitlendi (§14).

---

## 1. Yönetici Özeti

Gelişmiş aşama, MVP'nin genişletilmiş hâli **değildir**. Problem sınıfı değişti:

| | MVP (Temel) | Gelişmiş |
|---|---|---|
| Zaman çözünürlüğü | Gün | **Dakika** |
| Maliyet | Günlük kira + km | **Saatlik kira × kullanım süresi + km** |
| Kullanım süresi | — | **Çıkış elleçleme + bekleme + seyir + varış elleçleme** |
| Mesafe | Kuş uçuşu | **Verilen gerçek km + araç tipine göre seyir süresi** |
| Konsolidasyon | Yasak | **Serbest, her TM'de** |
| Teslim taahhüdü | Yok | **SLA + gecikme cezası (0,4 TL/desi/saat)** |
| TM kapasitesi | Yok | **Elleçleme kapasitesi + tır slot kapasitesi** |
| %10 min. doluluk | Var | **KALDIRILDI** |
| Araç/talep takibi | Yok | **Araç ID (V0001) + talep ID (D00001)** |
| Hat sayısı | 89 | **289** |
| Talep granülaritesi | Gün | **Gün × {09:00, 17:00}** |

**Sonuç:** Katman 1 (tahmin) uyarlanarak yaşar. **Katman 2'nin tamamı çöpe gider.** Katman 3 yeniden ve çok daha güçlü kurulur (§6).

Problem artık literatürdeki adıyla **konsolidasyonlu Servis Ağı Tasarımı** (Service Network Design).

---

## 2. MVP'den Devralınan Ders (mimariyi belirleyen)

MVP'de teslim edilen planın 687 satırının 300'ü fiziksel olarak geçersizdi: `waypoint.py` rotayı `[O, O2, D]` kuruyor, ama `hat2`'nin varışı `D2` rotaya hiç girmiyordu. 1.174.289 desi, aracın hiç uğramadığı şehirlere "teslim edildi" sayıldı — sıfır maliyetle. İnvariant kontrolü yakalamadı, çünkü yalnızca `atanan + karşılanamayan = tahmin` toplamına bakıyordu.

**Kök neden yazım hatası değil, mimari:**

1. **Rota birinci sınıf nesne değildi.** Güzergâh sonradan üretilen bir etiketti; hiçbir şey yük atamasını rotanın gerçekliğine bağlamıyordu.
2. **Optimizatör kendi kendini puanlıyordu.** Doğrulayıcı, üreticiyle aynı varsayımları paylaşıyordu; ortak yanılgıyı göremezdi.

Gelişmiş aşamada bu iki hata çok daha pahalıya patlar — artık zaman, elleçleme, SLA ve kapasite de yanlış hesaplanabilir. Mimarinin iki taşıyıcı kararı doğrudan buradan çıkıyor: §5.1 (servis nesnesi) ve §6 (bağımsız simülatör).

---

## 3. Kural Kaynağı — jüri cevaplarıyla kesinleşen

Bu maddeler soru-cevap belgesinden **doğrudan** alınmıştır. Varsayım değildir; kod bunlara birebir uymalıdır.

| Konu | Kural |
|---|---|
| **Kullanım süresi** | Çıkış elleçleme + **bekleme** + seyir + varış elleçleme. Örnek: 10.000 desi, 5 saat yol → 100 dk + 300 dk + 100 dk = **500 dk**. Ara duraktaki elleçleme de dahil. |
| **Yük vs araç beklemesi** | Yük TM'de bedava bekler (araç serbest bırakılır); *"elleçleme tamamlandığı an yeni araca yüklenmelidir gibi bir kural yoktur"*. Yalnızca **araç** beklemesi ücretlidir. |
| **Tır slotu** | Her dokunuşta tükenir. *"Döndüğü TM farklı TM olduğu için tabii ki de tır kapasitesini tüketir."* "Aynı araç = 1 slot" kuralı yalnızca **araç hareket etmeden boşaltılıp tekrar yüklenirse** geçerli. |
| **Tır slot kapsamı** | Yalnızca "Tır" tipi. Kiralık tırlar da dahil. Diğer araç türlerinde **hiçbir kapasite kısıtı yok**. |
| **Elleçleme kapasitesi** | TM'deki tüm elleçlemeleri (çıkış + varış) kapsar. Konsolidasyonda `x` indirip `y` yüklersen kapasiteden `x+y` düşer. Süre her ikisinde de 0,01 dk/desi. |
| **Gün-aşırı sefer — kota atfı** | Elleçleme, **yapıldığı TM'de yapıldığı gün** kotadan düşer. Jüri örneği: İstanbul'dan 29.06'da çıkan 10.000 desi Tekirdağ'a 30.06'da varırsa → 29.06'da İstanbul'dan 10.000, **30.06'da Tekirdağ'dan** 10.000. Yani gün-aşırı seferde çıkış ve varış **farklı günlerin** kotalarını tüketir. |
| **Gece yarısı geçişi** | Tek bir elleçleme işlemi gece yarısını aşarsa **oransal** bölünür. 23:30'da 10.000 desi başlarsa: o gün 3.000, ertesi gün 7.000. (Yukarıdaki kuraldan ayrıdır: o hangi *günün* kotası, bu tek işlemin *bölünmesi*.) |
| **Kuyruk yok** | *"Kapasitelere uygun olarak aynı anda araç yükleme/boşaltma yapılabilir."* TM'de FIFO/öncelik kuyruğu simüle edilmez; tek kısıt günlük kapasite. |
| **Elleçleme atomikliği** | Bir araçtaki tüm gönderiler aynı anda elleçlenir; desi bölünüp bir kısmı erken elleçlenmiş sayılamaz. |
| **SLA** | Başlangıç: orijinal çıkış TM'sindeki talep tamamlanma anı. Bitiş: **orijinal varış TM'sinde elleçlemenin bitiş anı**. 1 gün = tam 24 saat, 2 gün = 48 saat. Aradaki tüm adımlar (bekleme, konsolidasyon elleçlemeleri) dahil. |
| **SLA yuvarlama** | Üst tam saate. 09:00 sınırında 09:01 → **1 saatlik ceza**. |
| **%10 doluluk** | **Kaldırıldı.** *"Bu aşamada böyle bir kural bulunmamaktadır."* |
| **Zaman çözünürlüğü** | **Dakika.** Araç günün her dakikasında çıkabilir. Süreler **yukarı tam dakikaya** yuvarlanır (0,92 saat → 56 dk). Çıktıda saat formatı `SS:DD`. |
| **Tahmin ufku** | **29.06.2026 09:00 – 05.07.2026 17:00.** Teslim penceresi serbest: 5 Temmuz talebi 7 Temmuz'da teslim edilebilir, SLA cezası ödenerek. |
| **Tahmin kapsamı** | Geçmişte hiç görülmemiş TM çifti için tahmin üretilmez. Düşük değerli (<0,5) satırlar bile **sunulmalı**. |
| **Kiralık** | Uğrama yasak, rota sabit, dönüş yok, talep yetersiz olsa bile çıkmak zorunlu. Çıkış saatini biz seçeriz (o gün içinde). Konsolidasyon serbest (varışta indirip başka araca aktarma). |
| **Spot** | Sınırsız sefer, milk-run serbest, bir araca farklı varışlara giden yükler yüklenebilir. **Boş spot araç döndürülmez** (dönüş hesaba katılmaz). |
| **Talep bölme** | Serbest. `D00001-1`, `D00001-2`; ikinci kez bölünürse `D00001-1-1`. Tahmin ve plan dosyalarındaki ID'ler birebir eşleşmeli. |
| **Puanlama** | Tahmin gerçekle kıyaslanır. **Optimizasyon kendi tahminin üzerinden** değerlendirilir. |
| **Runtime** | Şartnamedeki 10 dk örnekmiş. Nihai sınır sonra belirlenecek; tahmin + planlama toplamı ölçülüyor. |

---

## 4. Ölçülmüş Veri Gerçekleri ve Bağlayıcı Kısıtlar

`teknofest26_gelismis.xlsx`: **66.024 talep** · 01.01–28.06.2026 (179 gün) · **289 hat** · 18 TM · ID `D00001…D66024`.

- Günlük toplam desi: ort. **814.319** · medyan 893.803 · min 104 · **max 2.637.199**
- **Desinin %91'i 17:00 slotunda** (132,99M) — 09:00 yalnızca 12,77M. Ortalama talep: 17:00 → 3.234 desi, 09:00 → 513 desi
- **Haftalık salınım ~20×**: Pazar 70–81 bin, Pazartesi 1,69 milyon
- **Trend**: Ocak 556k/gün → Haziran 975k/gün
- Tek talep max **78.420 desi** = 3,5 tır → bölme zorunlu
- Beklenen tahmin çıktısı: **289 hat × 7 gün × 2 slot = 4.046 satır**

`sehirler_arasi_lojistik.xlsx`: 306 yönlü çift (tam matris). 60–1548 km. Tır seyri 0,92–23,82 saat. SLA: 204 çift 1 gün, 102 çift 2 gün.

### 4.1 Tır slotu — EN SERT KISIT

Slot her dokunuşta tükenir (§3). Bütçe:

```
toplam slot                        69
kiralık tır: 10 araç × 2 dokunuş  −20
                                  ────
spot tıra kalan                    49  →  24 direkt sefer/gün
```

Bu **24 sefer bir üst sınırdır, ulaşılabilir bir hedef değil.** Slotlar TM bazındadır ve **havuzlanamaz** — Balıkesir'in 0'ı İstanbul'a devredilemez. Bir sefer çıkış TM'sinde 1 + varış TM'sinde 1 slot yediği için bu bir **derece-kısıtlı graf problemi**, basit bölme değil.

Gerçek tavan, slotu artan TM'lerin coğrafyasıyla belirleniyor. Spot tıra slot kalan TM'ler: Mersin 11, Kocaeli 9, Eskişehir 8, Mardin 5, Erzincan 5, Şanlıurfa 5, Manisa 3, İstanbul 2, Yalova 1. **Hem çıkışı hem varışı bu kümede olan talep, toplamın yalnızca %40'ı.**

> Spot tır ağın en fazla **%40'lık dilimine** girebilir → ortalama günde ~325.000 desi. Belgenin önceki sürümündeki "537.600 desi = %66" rakamı slot havuzlanabiliyor varsayıyordu; **yanlıştı**.

Talebin **%60'ı spot tır için yapısal olarak erişilemez.** Gerisi zorunlu olarak Kamyon/Hafif Kamyon/Kamyonet — bu tiplerde hiçbir sayı kısıtı yok.

**7 TM'de tır kapasitesi sıfır** (Kütahya, Isparta, Bilecik, Zonguldak, Karaman, Sivas, Denizli) → oralara tır hiç giremez; desinin %31'i etkileniyor.

**Kiralık tırlar batı hub'larının slotlarını bitiriyor:**

| TM | Kapasite | Kiralık tırın tükettiği | Spot tıra kalan |
|---|---|---|---|
| Balıkesir | 1 | 1 | **0** |
| Tekirdağ | 2 | 2 | **0** |
| Yalova | 4 | 3 | **1** |
| İstanbul | 10 | 8 | 2 |
| Manisa | 4 | 1 | 3 |
| Eskişehir | 10 | 2 | 8 |
| Kocaeli | 12 | 3 | 9 |
| Mersin | 11 | 0 | 11 |

`tir_kapasiteleri v2.xlsx` Balıkesir'e tam 1, Tekirdağ'a tam 2 veriyor — yani kiralık ihtiyacına **tam denk**. Bu, jürinin duyurduğu güncellemenin ta kendisi ve sıfır spot payı **kasıtlı**, veri hatası değil.

**Mimari sonuç (v4'te inceltildi):** Slot muhasebesi rota şekline bağlıdır. Tek O-D çifti için çok duraklı tır rotası daha fazla slot yer (3 durak = 3 slot, direkt = 2). Ama ara TM'ye **zaten hizmet gereken** durumda hesap tersine döner: A→B ve B→C taleplerini tek tırla zincirlemek, araç B'de hareket etmeden boşaltılıp yüklendiği için B'de 1 dokunuş yer (§3); iki bağımsız direkt sefer ise B'de 2 dokunuş yer. v3'ün "zincirlemenin hiçbir faydası yok" iddiası bu yüzden yanlıştı — kıt slotlu ara TM'lerde (İstanbul 2, Yalova 1) zincirleme gerçek kazançtır. Taban model yine de tırı direkt tutar: §4.3'ün SLA gerekçesi bağımsız olarak ayakta ve zincirleme, araç çizelgeleme bağı ekleyerek modeli karmaşıklaştırır. Zincirleme **LNS fırsat listesine** alındı (§5.5). Slot bağlayıcı kaynak olduğu için:

> **Tır direkt sefer yapmalı; konsolidasyon ve milk-run küçük araçların işidir.**

Bu, sezgiye ters ama veriden çıkan en değerli tasarım kuralı. Tır bütçesi, kıt kaynak olarak desi başına en çok kazandıran uzun ve dolu direkt hatlara tahsis edilmeli.

### 4.2 Elleçleme kapasitesi — pik günlerde BAĞLAYICI kısıt

v3 burada "en yüklü TM %63, kalan %40 konsolidasyon bütçesi" diyordu. Bu **ortalama** üzerinden doğru ama yanıltıcıdır; kısıtın gerçek yüzü pik günlerde görünür ve **plan haftası Pazartesi 29.06'da, haftanın en ağır gün tipiyle başlar.** Önce ortalama tablo:

| TM | Günlük elleçleme yükü | Kapasite | Kullanım |
|---|---|---|---|
| Şanlıurfa | 63.385 | 101.147 | %63 |
| Sivas | 53.876 | 86.518 | %62 |
| Kütahya | 39.660 | 64.732 | %61 |
| İstanbul | 238.501 | 394.786 | %60 |
| Yalova | 303.154 | 513.171 | %59 |

**Ölçülmüş pik gerçeği (v4):** plan haftasının proxy'si verideki son Pazartesi (22.06, 1,69M desi). Aynı-gün varsayımıyla (çıkış + varış elleçlemesi kendi gününde) **18 TM'nin 16'sı kapasite üstünde**:

| TM | Yük (çıkış+varış) | Kapasite | Kullanım |
|---|---|---|---|
| Karaman | 58.053 | 43.830 | **%132** |
| Kütahya | 84.341 | 64.732 | **%130** |
| Şanlıurfa | 126.424 | 101.147 | **%125** |
| İstanbul | 490.670 | 394.786 | **%124** |
| Yalova | 605.200 | 513.171 | **%118** |
| Tekirdağ | 348.175 | 297.576 | **%117** |
| *(+10 TM daha %100'ün üstünde; yalnız Denizli %90 ve Kocaeli %33 altında)* | | | |

Sadece **çıkış** elleçlemesi bile İstanbul'da kapasitenin %86'sı, Yalova'da %78'i. 179 günün 42'sinde en az bir TM aşımda; mutlak pik gün (01.06, 2,64M desi) birçok TM'de ~%180.

**Yapısal sonuç:** Pazartesi yükünün bir bölümünün elleçlemesi ertesi güne **taşmak zorundadır** — bekletme ve gün-yayma bir kenar durumu değil, planın merkez mekanizmasıdır. Salı, Pazartesi'nin varış elleçlemesini devraldığı için baskı haftaya yayılır. Konsolidasyon bütçesi pik günlerde **sıfır, hatta negatiftir**; konsolidasyon ancak hafta ortası/sonu boşluğunda ucuzdur. Model günlük ve pik üzerinden kurulmalı; kapasite aşımında yük bekler → SLA cezası (§4.3).

### 4.3 SLA — seyir açısından rahat; pik günde kapasite kaynaklı ceza yapısal

Tam yüklü araçta, çıkış + varış elleçlemesi dahil, en kötü hâl:

| Araç | Elleçleme (tek yön) | SLA=1g max toplam | İhlal | SLA=2g max toplam | İhlal |
|---|---|---|---|---|---|
| Tır | 3,73 h | 19,36 h / 24 h | **0/204** | 31,29 h / 48 h | **0/102** |
| Kamyon | 2,00 h | 15,04 h / 24 h | 0/204 | 26,11 h / 48 h | 0/102 |
| Kamyonet | 0,93 h | 11,53 h / 24 h | 0/204 | 21,22 h / 48 h | 0/102 |

Tablo yalnız **seyir + elleçleme** penceresine bakar: hiçbir hat, zamanında çıkan dolu araç için SLA'yı yapısal olarak ihlal etmez. Ama §4.2'nin pik günü resmi değiştirir: Pazartesi yükünün bir kısmı kapasite yüzünden beklemek zorunda olduğundan, **pik gün taleplerinin bir bölümünde SLA cezası kaçınılmazdır** — kimin bekleyeceğini (hangi talep, hangi TM) seçmek optimizasyonun ta kendisidir.

**Her gecikme cezası bir planlama tercihidir.** SLA sert kısıt değil, amaç fonksiyonunda ceza terimi olmalı — böylece optimizatör "şimdi az dolu çıkar" ile "bekletip konsolide et, cezayı öde" arasındaki takası kendisi çözer.

**Konsolidasyonun SLA maliyeti:** ara durakta indir+yükle = 2× ek elleçleme.

```
tam tır, tek yönlü elleçleme        3,73 h  (224 dk)
direkt sefer   : 2 × 3,73        =  7,47 h
konsolidasyonlu: 4 × 3,73        = 14,93 h
SLA=1g max seyir 11,89 + 14,93   = 26,82 h  >  24 h bütçe  ✗
```

Yani **tam yüklü tırla konsolidasyon 1-günlük hatlarda cezaya girer.** Küçük araçlarda elleçleme çok daha ucuz (Kamyonet 0,93 h) ve rahat sığar. §4.1'in "konsolidasyon küçük araçların işidir" sonucunu bağımsız olarak doğruluyor.

### 4.4 Araç ekonomisi

Kullanım süresi **elleçlemeyi içerir** (§3) ve elleçleme yüke bağlıdır — dolayısıyla desi başına maliyet, aracın *kapasitesiyle birlikte büyüyen* bir elleçleme cezası taşır. Tam yükte, 194 km referans hatta:

| Araç | Kapasite | Seyir | Elleçleme (2×) | Kullanım | Spot TL | **Spot TL/desi** |
|---|---|---|---|---|---|---|
| Tır | 22.400 | 2,98 h | **7,47 h** | 10,45 h | 9.943 | **0,4439** |
| Kamyon | 12.000 | 2,77 h | 4,00 h | 6,77 h | 6.229 | 0,5190 |
| Hafif Kamyon | 7.200 | 2,59 h | 2,40 h | 4,99 h | 5.699 | 0,7916 |
| Kamyonet | 5.600 | 2,42 h | 1,87 h | 4,29 h | 4.340 | 0,7751 |

> **Uyarı:** bu tablonun önceki sürümü elleçlemeyi atlıyordu ve tırı %58 ucuz gösteriyordu (0,2814). Ondan türetilen iki sonuç da yanlıştı; ikisi de aşağıda düzeltildi.

**Tır "açık ara en ucuz" değil — avantajı mesafeye bağlı.** Elleçleme sabit bir zaman cezası olduğu için kısa hatlarda tırı boğuyor; km maliyeti ise uzun hatlarda tırın kapasitesi lehine ölçekleniyor:

| km | Tır | Kamyon | H. Kamyon | Kamyonet | Tır'ın Kamyon'a üstünlüğü |
|---|---|---|---|---|---|
| 60 | 0,2495 | **0,2339** | 0,3287 | 0,2853 | **−%6,7 — Kamyon kazanıyor** |
| 154 | **0,3860** | 0,4339 | 0,6531 | 0,6292 | %11,1 |
| 298 | **0,5948** | 0,7406 | 1,1503 | 1,1557 | %19,7 |
| 495 | **0,8808** | 1,1598 | 1,8307 | 1,8758 | %24,1 |
| 809 | **1,3364** | 1,8284 | 2,9151 | 3,0236 | %26,9 |
| 1548 | **2,4086** | 3,4015 | 5,4667 | 5,7256 | %29,2 |

> **Tasarım kuralı:** kıt tır slotu **uzun hatlara** tahsis edilmeli. 60 km'lik bir hatta tır kullanmak hem Kamyon'dan pahalı hem de iki slot yakıyor — çifte kayıp. §9'un slot tahsisi bunu tasarruf sıralamasıyla zaten yakalar, ama kuralın kendisi bilinmeli.

**Hafif Kamyon baskın olarak kötü DEĞİL.** Önceki sürüm öyle iddia ediyordu; elleçleme dahil edilince çöküyor. 298 km'de:

| Yük | 1 Hafif Kamyon | Kamyonet alternatifi | Kazanan |
|---|---|---|---|
| 5.600 desi | 8.088 TL | 1 × 6.472 TL | Kamyonet |
| 6.000 desi | 8.137 TL | 2 × = 12.600 TL | **Hafif Kamyon** |
| 7.200 desi | 8.282 TL | 2 × = 12.680 TL | **Hafif Kamyon** |

**5.600–7.200 desi aralığında Hafif Kamyon açıkça kazanıyor** — Kamyonet'e sığmayan yük iki araç gerektiriyor. Havuzda kalmalı ve çıkması **normaldir**.

**Bekleme para yakıyor:** boşta bekleyen spot tır saatte 487,50 TL (Kamyon 318,25 · H. Kamyon 364,58 · Kamyonet 197,92). Ama bu yalnızca **araç** beklemesi için geçerli — yük bedava bekler (§3). Bu ayrım modelin kalbinde olmalı: konsolidasyonda aracı bekletme, **yükü** beklet.

---

## 5. Katman Mimarisi

```
Ham veri (5 excel + 66k talep)
   │
   ▼
┌──────────────────────────────────────────────────┐
│ Katman 0 · Veri & Kısıt Çekirdeği               │
│   immutable, doğrulanmış, tek kaynak             │
└──────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────┐
│ Katman 1 · Talep Tahmini                         │
│   (tarih, çıkış, varış, slot) → desi             │
│   29.06 09:00 – 05.07 17:00 · 4.046 satır        │
│   saf WAPE · DOW + trend · talep ID              │
└──────────────────────────────────────────────────┘
   │  Talep-tahmini.xlsx  +  iç talep nesneleri
   ▼
┌──────────────────────────────────────────────────┐
│ Katman 2 · Servis Ağı Tasarımı                   │
│  ① Servis havuzu (rota + kalkış anı + tip)       │
│  ② Set-partitioning MILP (seçim + akış)          │
│  ③ LNS ile iyileştirme                           │
└──────────────────────────────────────────────────┘
   │  Plan nesnesi
   ▼
┌──────────────────────────────────────────────────┐
│ Katman 3 · BAĞIMSIZ SİMÜLATÖR + Kalite Kapısı    │
│   planı sıfırdan oynatır, maliyeti kendi hesaplar│
│   optimizatör ≠ simülatör → teslim BLOKLANIR     │
└──────────────────────────────────────────────────┘
   │
   ▼
Tasima-plani.xlsx · Talep-tahmini.xlsx
```

**Katman 0.** MVP'de araç parametreleri `config.py`'ye elle kopyalanmıştı. Artık 5 ayrı Excel'den geliyorlar; elle kopyalamak, kaynakla sessizce ayrışan bir plan üretir. Tüm kısıt verisi okunur, yükleme anında doğrulanır, **değişmez** bir kısıt nesnesi üretilir. `config.py`'de yalnızca gerçek sabitler kalır: elleçleme hızı (0,01 dk/desi), SLA katsayısı (0,4 TL), talep saatleri, ID formatları, tahmin ufku.

### 5.1 Taşıyıcı karar: Servis birinci sınıf nesnedir

MVP hatasının panzehiri (§2).

```python
@dataclass(frozen=True)
class Servis:
    arac_tipi:  str
    kiralik:    bool
    duraklar:   tuple[str, ...]     # sıralı TM listesi — DOĞRULANMIŞ
    cikis_ani:  datetime            # dakika çözünürlüğü

    def bacaklar(self) -> list[Bacak]: ...
    def ziyaret_ani(self, tm: str) -> datetime: ...
```

Tek değişmez kural:

> **Bir talep, ancak `duraklar` içinde çıkış TM'sini varış TM'sinden ÖNCE içeren bir servise bağlanabilir.**

`Servis.talep_bagla()` içinde yapısal olarak zorlanır; başarısızsa exception atılır, sessizce atlanmaz. MVP'nin 300 hayalet satırı bu tek kuralla imkânsız hâle gelir. `maliyet` asla elle yazılmaz, `Servis`'ten türetilir ve Katman 3 bağımsızca yeniden hesaplar.

### 5.2 Zaman modeli

Jüri: zaman çözünürlüğü **dakika**, süreler **yukarı tam dakikaya** yuvarlanır.

- Seyir: `⌈saat × 60⌉` dk (0,92 h → 56 dk)
- Elleçleme: `⌈desi × 0,01⌉` dk — **araç bazlı**, aracın indirdiği/yüklediği toplam desi üzerinden; o araçtan inen her talep aynı varış anını alır (§3 atomiklik)
- SLA gecikmesi: `⌈saat⌉`, 1 dk gecikme = 1 saat ceza

Bir talebin yaşam çizgisi:

```
talep doğar (09:00 / 17:00) — SLA saati başlar
   │  [yük bekleyebilir — ARAÇ maliyeti YOK, yalnız SLA saati işler]
   ▼
çıkış elleçleme (⌈desi × 0,01⌉ dk)  → TM kapasitesinden düşer, araç saati işler
   ▼
seyir (⌈saat × 60⌉ dk)
   ▼
varış elleçleme (⌈desi × 0,01⌉ dk)  → TM kapasitesinden düşer, araç saati işler
   ▼
├─ varış TM = hedef  → TESLİM. SLA saati durur.
└─ konsolidasyon TM  → yük bedava bekler, sonra yeni araca binebilir
                        (elleçleme kapasitesinden x+y düşer)
```

**Elleçleme atomikliğinin gizli maliyeti:** 22.400 desilik tır 224 dk (3,73 saat) elleçlenir ve içindeki *en acil talep de* bu süreyi bekler. Bu, "büyük aracı doldur" kararını sessizce cezalandırır. Modelde mutlaka olmalı; yoksa optimizatör tırı sistematik olarak fazla sever ve SLA cezasını olduğundan düşük tahmin eder.

**Gece yarısı:** elleçleme kapasitesi **oransal** bölünür (§3). Bu, "gün" kavramını kapasite muhasebesinde sürekli bir zaman ekseni üzerine oturtmayı gerektirir — MVP'nin ayrık gün mantığı burada çalışmaz.

### 5.3 Katman 2 · ① Servis havuzu

Aday servisler üretilir, hepsi değil. Filtreler:

- **Tır → yalnız direkt (2 durak).** §4.1'den: çok duraklı tır fazladan slot yer ve §4.3'ten: tam yüklü tır konsolidasyonu 1-günlük SLA'yı aşar. Tırın milk-run yapması iki bağımsız nedenle kötü.
- **Küçük araçlar → ≤3 durak** (O + ≤2 ara). Konsolidasyonun asıl aracı bunlar.
- **Sapma:** kümülatif mesafe ≤ direkt × 1,3.
- **Tır yasağı:** rotasında tır kapasitesi 0 olan TM bulunan tır servisleri baştan elenir (7 TM).
- **Kalkış anları:** talep doğuş anı + elleçleme süresine dayalı aday ızgara. Dakika çözünürlüğü *modelin* değil *çıktının* gereği — havuz için akıllı aday üretimi şart, yoksa 10.080 dakikalık ufukta kombinatorik patlar.
- **Kiralık servisler:** havuza **sabit** girer (zorunlu). Seçim değişkeni değil, veri. Yalnız kalkış saati serbest (§3).

### 5.4 Katman 2 · ② Set-partitioning MILP

**Değişkenler**
- `x[s] ∈ ℤ₊` — servis `s` kaç kez çalışır
- `f[d, s, bacak] ∈ ℝ₊` — talep `d`'nin o bacakta taşınan desisi
- `g[d, tm, t] ∈ ℝ₊` — talep `d`'nin `tm`'de bekleyen desisi (bedava, §3)
- `z[d, t] ∈ ℝ₊` — `t` anında teslim edilen desi (SLA cezası buradan)

**Amaç**
```
min  Σ_s x[s]·maliyet(s)  +  0,4 · Σ_d,t z[d,t] · ⌈gecikme(d,t)⌉
```
Kiralık maliyeti sabit terimdir (zorunlu) — optimizasyonu yönlendirmez, toplamda raporlanır.

**Kısıtlar**
1. Akış korunumu — her (talep, TM, an) düğümünde giren = çıkan + bekleyen
2. Talep karşılama — `Σ_t z[d,t] = desi[d]` (gecikse de tamamı teslim edilir)
3. Araç kapasitesi — her bacakta `Σ_d f[d,s,bacak] ≤ kapasite(s)·x[s]`
4. **Elleçleme kapasitesi** — her TM-gün: `Σ (o TM'de o gün inen + binen desi) ≤ kapasite[tm]`. İki incelik (§3): elleçleme **yapıldığı günün** kotasına yazılır — gün-aşırı seferde çıkış ve varış farklı günleri tüketir; ve gece yarısını aşan tek işlem **oransal** bölünür. Yani kota muhasebesi servisin gününe değil, **her elleçleme olayının kendi anına** bağlıdır.
5. **Tır slotu** — her TM-gün: `Σ_s x[s] · dokunuş(s, tm)` ≤ `tir_kapasitesi[tm]` — dokunuş(s, tm) = servisin o TM'yi ziyaret sayısı; `x[s]` ile çarpım, servis *sayısını* değil araç *adedini* sayar
6. Kiralık — `x[s] = verilen_sayı`

**Kısıt 5 artık kolay.** v1'de "benzersiz araç sayımı" nedeniyle iteratif çözüm gerekiyordu; jüri cevabı slotu **dokunuş başına** tanımladığı için doğrudan doğrusal bir kısıt oldu. Taban modelde her servis bağımsız bir araç kiralamasıdır; araç ID'leri servis başına üretilir. **Dikkat (v4):** bu bir modelleme sadeleştirmesidir, kural gerçeği değil — hareket etmeden boşalt+yükle zincirlemesi ara TM'de 1 slot kazandırır (§4.1). Taban model bu kazancı bilerek masada bırakır; LNS sonradan kovalayabilir (§5.5).

**Yük-bağımlı süre — v4'ün kapattığı açık.** Elleçleme süresi araca binen desiye bağlıdır (`⌈desi × 0,01⌉` dk) ve desi bir karar değişkenidir (`f`). Yani varış anları — dolayısıyla SLA cezası ve sonraki bacakların zamanlaması — akışa bağlıdır; zaman ızgarası çözümden önce bilinemez. Çözüm iki parçalıdır:

- **Maliyet lineerleşir:** araç maliyeti = sabit kısım (seyir süresi × saatlik kira + km × km maliyeti) + **desi başına değişken elleçleme terimi** (saatlik kira × 0,0001 saat/desi × yüklenen+indirilen desi). Katsayı `f` ile çarpılır — tamamen doğrusal.
- **Zaman sabitlenir:** her servis adayının elleçleme süreleri **tam kapasite varsayımıyla** hesaplanır. Muhafazakârdır — süreyi asla eksik, SLA'yı asla iyimser göstermez. Çözümden sonra bir **post-pass**, gerçek yüklerle süreleri ve kalkış/varış anlarını yeniden hesaplar (kalkışları SLA'ya göre geri çeker); Katman 3'e giden plan post-pass çıktısıdır ve §6 kapısı bu plan üzerinde çalışır.

Bu tanım olmadan optimizatör ile simülatör yapısal olarak farklı süre hesaplar ve §6'nın kuruş-kuruşuna kapısı her planda patlar — v3'ün en büyük açığı buydu.

**Ölçek uyarısı — en büyük risk.** 289 hat × 2 slot × 7 gün ≈ 4.000 emtia. Naif formülasyon çözülmez. Zorunlu küçültmeler:

- **Emtia toplulaştırma:** talebi `(varış TM, SLA bitiş anı)` çiftinde topla → ~250 emtia. Talep ID'leri çözüm sonrası akış ayrıştırmasıyla geri atanır (çıktı formatı için gerekli).
- **Zaman ızgarası:** modelde dakika değil, aday kalkış anlarından türeyen **olay-güdümlü** düğümler. Çıktı dakika hassasiyetinde olur; model her dakikayı düğüm yapmaz.
- **Kayan pencere:** SLA ≤ 2 gün olduğu için 3 günlük pencerelerle çöz, ilk günü sabitle, ilerle. Küresel optimallikten feragat — kabul edilebilir takas.
- **Solver:** CBC yetersiz kalır. **HiGHS** (`highspy`) veya **OR-Tools CP-SAT**. CP-SAT tercih edilir: iyi ilk çözümü hızlı bulur ve runtime sınırı (§3) belirsiz.

Bu risk gerçek — sigortası §9'daki **greedy taban çizgisi**, ve yol haritasında (§11) MILP'ten önce yazılır.

### 5.5 Katman 2 · ③ LNS

Zaman kalırsa. Böl-onar: rastgele bir TM-gün seçilir, oradaki servisler yıkılır, MILP ile küçük ölçekte yeniden kurulur. Ucuz, güvenli, monoton iyileşir. **Katman 3 geçmeden hiçbir LNS çıktısı kabul edilmez.**

Fırsat listesi (v4): ① kıt slotlu ara TM'lerde **tır zincirlemesi** — hareket etmeden boşalt+yükle 1 dokunuş sayıldığı için slot kazandırır (§4.1); ② pik gün bekletme desenlerinin yeniden dağıtımı (§4.2).

---

## 6. Katman 3 — Bağımsız Simülatör (mimarinin en önemli parçası)

MVP'nin gerçek hatası hayalet rota değil, **optimizatörün kendi kendini puanlaması**ydı.

**Karar: Katman 3, yalnızca `Tasima-plani.xlsx`'i okuyan bağımsız bir kesikli-olay simülatörüdür.**

- Girdi: **sadece teslim edilecek çıktı dosyası** + ham kısıt verisi. Katman 2'nin hiçbir iç nesnesini, ara sonucunu veya yardımcı fonksiyonunu **import etmez**.
- Katman 2 ile **hiçbir kod paylaşmaz** — maliyet formülü dahil, kasıtlı olarak yeniden yazılır. Kod paylaşımı, ortak hatayı görünmez yapan şeydir.
- Sıfırdan oynatır ve bağımsızca yeniden hesaplar:
  - Her aracın (V ID) zaman çizelgesi — çakışma? Araç aynı anda iki yerde mi?
  - Her bacakta kapasite aşımı
  - Her TM-gün elleçleme kapasitesi (konsolidasyon `x+y`, gün-aşırıda her elleçleme kendi gününe, gece yarısını aşan işlem oransal — §3)
  - Her TM-gün tır dokunuş sayısı
  - Her talebin teslim anı → `⌈gecikme⌉` → ceza
  - Kullanım süresi = çıkış elleçleme + bekleme + seyir + varış elleçleme → toplam maliyet
- **Rota geçerliliği:** her talebin aracı, çıkış TM'sini varış TM'sinden önce ziyaret ediyor mu? (MVP'yi öldüren kontrol.)
- **Talep bütünlüğü:** `Σ bölünmüş parçalar = tahmin edilen desi`; her `D0000X-k` tam olarak bir kez taşınmış mı; tahmin ve plan dosyalarındaki ID'ler birebir eşleşiyor mu (§3).
- **Format kapısı:** şablon dosyalarla birebir sütun kıyası + muhasebe invariantı (§8.2): `Σ Toplam maliyet`, `Σ SLA cezası` bağımsız hesapla uyuşuyor mu. Şartname: *"formata uymayan takımların sonuçları kesinlikle değerlendirmeye alınmayacaktır."*

**Kapı kuralı:** simülatör maliyeti ile optimizatör maliyeti **kuruşu kuruşuna** uyuşmuyorsa teslim bloklanır. Uyuşmazlık uyarı değil, hatadır — biri yanlış hesaplıyordur ve hangisi olduğu bilinmeden teslim edilemez.

---

## 7. Katman 1 — Tahmin (uyarlanır)

MVP'nin global LightGBM + direct multi-step + seed ensemble omurgası yaşar.

**Hedef:** `(tarih, çıkış, varış, slot) → desi`, slot ∈ {09:00, 17:00}. Ufuk **29.06 09:00 – 05.07 17:00**. Çıktı **4.046 satır** (289 × 7 × 2); düşük değerli satırlar bile sunulur (§3).

**Metrik: saf WAPE.** MAPE bu veride patlıyor (min desi 17, sıfıra yakın paydalar).

**v1'in "maliyet-farkında kuantil" fikri iptal edildi.** Jüri: *"Optimizasyon başarınızı kendi tahminlediğiniz talepler üzerinden değerlendiriyoruz. Tahminleriniz gerçek tahminlerle karşılaştırılmaktadır."* İki katman puanlama tarafından **kasıtlı olarak ayrılmış**:

- Tahmini bilerek yukarı/aşağı kaydırmak SLA riskini yönetmez — SLA cezası zaten *senin* tahminin üzerinden hesaplanıyor
- Az tahmin → az planla → düşük maliyet, ama bu kazanç değil oyunlama; ve tahmin skoru gerçekle kıyaslandığı için doğrudan cezalandırılıyor

Dolayısıyla **tahmin saf doğruluğu kovalar, optimizatör de tahmini veri kabul eder.** Uçtan uca bağlama bu puanlama şeması altında yanlış olurdu.

**Slot dengesizliği (%91 / %9) mimari karar gerektirir.** Tek model + `slot` feature'ı mı, iki ayrı model mi? Öneri: **tek global model + slot feature**. 09:00'ın kendi başına yeterli sinyali yok (ort. 513 desi, gürültü baskın) ama 17:00 ile paylaştığı hat/mevsim yapısı var; ayrı model 09:00'ı gürültüye ezdirir. Karşı-deney yine de yapılmalı — ucuz.

**Feature'lar (ölçülmüş yapıdan):**
- **Haftanın günü — en güçlü sinyal.** Pazar 70k ↔ Pazartesi 1,69M (20×)
- **Trend**: Ocak 556k → Haziran 975k. Direct multi-step ufuk feature'ı ile yakalanır; log-dönüşüm test edilmeli
- Slot × DOW etkileşimi
- Hat kimliği (289 hat), lag/rolling — MVP'den devam

**Talep ID:** `D00001…` sıralı, deterministik, `(tarih, slot, çıkış, varış)` sırasına göre. Katman 3'ün eşleşme kontrolünde.

**Backtest protokolü.** MVP'den devralınır ve sıkılaştırılır:
- **Walk-forward**, 5 kat, eğitim→test arası **7 gün boşluk** (sızıntı önlemi). Ufuk 7 gün olduğu için boşluk ufka eşit olmalı.
- Her katın test penceresi 7 gün × 2 slot — gerçek teslim koşuluyla birebir aynı şekil.
- **Son kat mutlaka Haziran sonu** olmalı: trend Ocak→Haziran %75 arttığı için eski katlarda iyi görünen model güncel rejimde kötü olabilir.
- Metrik WAPE; MAPE yalnız referans olarak raporlanır (bu veride patlıyor).
- **Naif taban çizgisi zorunlu:** "geçen haftanın aynı günü, aynı slotu". DOW etkisi 20× olduğu için bu taban şaşırtıcı derecede güçlüdür; model onu yenmiyorsa karmaşıklık boşuna.

---

## 8. Çıktı Şeması ve Muhasebe Kuralı

Şartname: *"bu formata uymayan takımların sonuçları kesinlikle değerlendirmeye alınmayacaktır."* Bu bölüm şablon dosyaların incelenmesinden türetilmiştir; tahmin değil, ölçüm.

### 8.1 Tasima-plani.xlsx — satır birimi

16 sütun. Şablonun kendisi satır birimini ele veriyor: **(Araç ID, bacak, Talep ID)** üçlüsü. Örnek satırlar:

| Araç ID | Araç Tipi | Araç türü | Çıkış | Varış | Talep ID | Taşınan Desi |
|---|---|---|---|---|---|---|
| V0001 | Spot | Tır | İstanbul | Yalova | D00001 | 3,0 |
| V0001 | Spot | Tır | İstanbul | Yalova | D00002 | 4,0 |
| V0001 | Spot | Tır | Yalova | Eskişehir | D00002 | 4,0 |

D00002 aynı araçta iki bacak boyunca gidiyor → **her bacak × her talep bir satır.** Bir bacakta `n` talep varsa `n` satır; aynı bacak bilgileri tekrar eder.

- `Araç Tipi` ∈ {Spot, Kiralık} · `Araç türü` ∈ {Tır, Kamyon, Hafif Kamyon, Kamyonet}
- `Çıkış Tarihi` / `Varış Tarihi` ayrı sütunlar → gün aşırı sefer doğal olarak ifade edilir
- `Çıkış Saati` / `Varış Saati` → **`SS:DD`** (jüri cevabı; şablondaki saniyeli format değil)

**Şablondaki tutarsızlık:** 4. satırda `V0001` hem `Tır` hem `Kamyon` görünüyor. Bir araç tür değiştiremez; bu şablon hatasıdır. **Kural: bir `Araç ID` tam olarak bir araç türüne ve bir tipe sahiptir.** Katman 3 bunu doğrular. Şablondan aşırı çıkarım yapılmaz.

### 8.2 Muhasebe invariantı — her maliyet tam bir kez

`Toplam maliyet` sütunu, satır birimi (araç, bacak, talep) iken aracın maliyeti **araç bazlıdır**. Tekrar edilirse sütun toplamı şişer. Tek tutarlı kural:

> **Her sayısal büyüklük, sahibi olan birimin tam olarak bir satırında görünür; diğerlerinde 0. Sütun toplamı = gerçek toplam.**

MVP'de aynı karar verilmişti ve geçti: `toplam_maliyet = tam_plan["Maliyet"].sum()`, uğramada maliyet `hat1` satırına yazılıp `hat2` satırına 0 konuyordu. Bu bir jüri sorusu değil, muhasebe zorunluluğu — alternatifi toplamı bozar.

Uygulama:

| Sütun | Sahibi | Nereye yazılır |
|---|---|---|
| `Toplam maliyet` | Araç (tüm güzergâh) | Aracın **ilk** satırına tam değer, diğer satırlarına 0 |
| `SLA cezası` | Talep | Talebin **nihai teslim** bacağının satırına, diğer bacaklarına 0 |
| `Yolculuk süresi` | Bacak | Bacağın ilk satırına, aynı bacağın diğer talep satırlarına 0 |
| `Varış/Çıkış elleçleme süresi` | Bacak (araç bazlı, §5.2) | Bacağın ilk satırına, diğerlerine 0 |
| `Taşınan Desi` | (bacak, talep) | Her satıra kendi değeri — zaten satır birimiyle birebir |

Katman 3 üç toplamı bağımsızca doğrular: `Σ Toplam maliyet` = araç maliyetleri toplamı, `Σ SLA cezası` = ceza toplamı, `Σ Taşınan Desi` bacak bazında araç kapasitesini aşmıyor.

### 8.3 Talep-tahmini.xlsx

6 sütun: `Talep ID`, `Tarih`, `Talep Tamamlama Saati`, `Çıkış Transfer Merkezi`, `Varış Transfer Merkezi`, `Tahmin Edilen Desi`.

**İki dosyanın formatları farklıdır** — şablonlar birebir izlenir:
- `Tarih` → **`GG.AA.YYYY`** metin (`01.04.2026`)
- `Talep Tamamlama Saati` → **`SS:DD:ss`** metin (`09:00:00`) — plan dosyasındaki `SS:DD`'den farklı
- **09:00 ve 17:00 ayrı satırlarda** (jüri: *"Evet, 09.00 ve 17.00 olarak ayrı satırlarda göstermeniz gerekmektedir"*) — birleştirilmiş günlük toplam **kabul edilmez**
- 4.046 satır (289 hat × 7 gün × 2 slot); değeri <0,5 olan satırlar bile **sunulur** (§3)

`Talep ID` ile plan dosyasındaki ID'ler **birebir eşleşmeli**. Bölünmüş parçalar (`D00001-1`) plan tarafında görünür; kök ID tahmin tarafında.

### 8.4 Teslim paketi — üç şey, iki dosya

Şartname: *"Bize göndereceğiniz çözüm dosyasında sizden şunları bekliyoruz: 1. Çözüm için kullandığınız **kaynak kodlarınız** 2. Taşıma planı"* — artı talep tahmini. Yani teslim edilen **kaynak kodun kendisi de bir çıktıdır**, yardımcı malzeme değil:

- Repo, klonlanıp tek komutla çalışabilmeli (MVP'de `python main.py` idi — bu iyi karardı, korunur)
- Ham veri repoda olmalı ki jüri ayrı dosya aramasın (MVP'de öyleydi)
- Runtime ölçülüyor ve **tahmin + planlama toplamı** sayılıyor (§3); ikisi tek girişten çalışmalı ki ölçüm anlamlı olsun
- Kod, ürettiği çıktının kanıtı olmalı: `main.py` çalıştırıldığında teslim edilen iki xlsx birebir yeniden üretilmeli (determinizm — seed sabit)

**Üçüncü veri dosyası yok.** MVP'de `Karşılanamayan_Yük.xlsx` vardı. Gelişmiş aşamada yok: yalnız 2 dosya isteniyor ve %10 doluluk kuralı kalktığı için karşılanamayan yük kavramı da yok — tüm yük teslim edilir, geç kalırsa SLA cezası ödenir (§3). `output_writer` bu dosyayı üretmemelidir.

### 8.5 Şablondan/veriden türeyen diğer kararlar

Bunlar jüriye sorulmaz; veriden ve kurallardan çıkar:

- **Spot aracın konumlanması:** hiçbir kuralda boş konumlanma maliyeti yok ve *"boş spot araçları döndürmeyiniz"* deniyor → spot araç çıkış TM'sinde kiralanmış kabul edilir, konumlanma maliyeti **sıfır**.
- **Kiralık çıkış saati:** *"Kiralık aracın çıkış saatini o gün içinde olacak şekilde belirleyiniz"* → bizim **karar değişkenimiz**. Kiralık tırlar slot ve elleçleme kapasitesi tüketirken zamanlaması da esnek; MILP'te `x[s]` sabit ama `cikis_ani` serbest.
- **Kocaeli:** 4.800 çıkışlı talep, **0 varışlı** (jüri: *"Veriseti görüldüğü gibidir"*). Yani hiçbir talep Kocaeli'de bitmez — ama konsolidasyon talep değildir. Kocaeli'nin 12 tır slotu (ağın en yükseği) **aktarma hub'ı** olarak kullanılabilir; model bunu yasaklamamalı. Tahmin tarafında Kocaeli varışlı satır **üretilmez** (geçmişte yok).
- **Hafif Kamyon:** havuzda kalır ve çıkması normaldir — 5.600–7.200 desi aralığında Kamyonet'i yener (§4.4). Belgenin önceki sürümü bunun tersini iddia ediyordu; elleçleme atlandığı için oluşan bir yanılgıydı.

---

## 9. Greedy Taban Çizgisi (sigorta planı)

Yol haritasının 4. maddesi ve MILP oturmazsa teslim edilecek çözüm. Bu yüzden **tanımlı olmak zorunda** — v2'de sadece adı vardı.

**Tasarım ilkesi: konsolidasyon yok, uğrama yok, yalnız direkt sefer.** Geçerliliği kanıtlaması kolay, tüm kısıtları sağlar, ve §4.1'in "tır direkt sefer yapmalı" sonucuyla zaten hizalı.

```
1. Kiralık servisleri yerleştir (zorunlu)
   - her kiralık araç kendi hattında, o gün içinde bir kalkış anı seç
   - kalkış anı: kendi hattındaki talebin doğuş anı + çıkış elleçleme
   - taşıdığı desi = min(hattaki talep, kapasite); kalanı spot'a devret
   - tükettiği tır slotunu ve elleçleme kapasitesini düş

2. Tır slot bütçesini tahsis et (kıt kaynak — §4.1)
   - kalan her (gün, hat) talebi için "tır tasarrufu" hesapla:
       tasarruf = (en ucuz tırsız plan maliyeti) − (tır planı maliyeti)
     maliyetler TAM formülle (elleçleme dahil) — §4.4'ün ilk sürümü bunu atlayıp
     tırı %58 ucuz göstermişti
   - tasarrufa göre azalan sırala → doğal olarak UZUN HATLAR öne geçer (§4.4:
     tırın avantajı 60 km'de negatif, 1548 km'de %29). Kısa hatta tır ataması
     tasarruf negatif olduğu için kendiliğinden elenir
   - slot bütçesi (çıkış TM'de 1 + varış TM'de 1) yettiği sürece tır ata
   - bütçe TM BAZINDA tutulur, havuzlanmaz (§4.1)
   - tır kapasitesi 0 olan TM'leri baştan ele

3. Kalan yükü tırsız araçlarla taşı (limitsiz)
   - her (gün, hat, slot) için: desi'yi araç kapasitelerine böl
   - tam araçlar için desi başına en ucuz tip; artık için en ucuz TEK araç
   - %10 doluluk kuralı YOK → artık yük atılmaz, en küçük araçla gider

4. Elleçleme kapasitesini yönet (PİK GÜNLERDE MERKEZ ADIM — §4.2)
   - TM-gün kapasitesi aşılıyorsa, en düşük SLA baskısı olan yükü ertesi güne ötele
   - Pazartesi bu adım istisna değil kuraldır: yükün bir bölümü yapısal olarak taşar;
     kimin bekleyeceğini ceza/desi sıralamasıyla seç (2 günlük SLA hatları önce)
   - öteleme SLA cezası üretir; ceza < ek araç maliyeti olduğu sürece kabul

5. Kalkış anlarını SLA'ya göre geriye doğru çizelgele
   - hedef: varış elleçlemesi SLA sınırından önce bitsin
   - mümkünse talep doğduğu an çık (yük beklemesi bedava ama SLA saati işliyor)
```

Bu plan konsolidasyondan gelen kazancı kaçırır ama **geçerlidir ve teslim edilebilir**. MILP'in kıyas zemini de budur: MILP bunu yenemiyorsa MILP'te hata vardır.

---

## 10. Test Stratejisi

%44'ü geçersiz bir plan teslim etmiş bir projede bu bölümün olmaması, v2'nin en büyük açığıydı.

**Katman 3 simülatörü bir test değildir — üretim kapısıdır.** Testler onun *altında* durur.

| Seviye | Ne test edilir | Neden |
|---|---|---|
| **Birim** | `maliyet()` — jürinin verdiği örnekler birebir | Jüri iki somut örnek verdi: 10.000 desi + 5 saat = **500 dk**; 1 saat beklemeli hâli = **560 dk**. Bunlar altın test vektörü. |
| **Birim** | `⌈⌉` yuvarlamaları | 0,92 saat → 56 dk; 1 dk gecikme → 1 saat ceza; elleçleme `⌈desi × 0,01⌉` |
| **Birim** | Gece yarısı oransal bölme | Jüri örneği: 23:30'da 10.000 desi → 3.000 / 7.000 |
| **Özellik** | `Servis.talep_bagla()` — O, D'den önce değilse **daima** exception | MVP'yi öldüren hata. Rastgele rota + rastgele talep üret, hiçbiri sessiz geçmesin. |
| **Özellik** | Muhasebe invariantı (§8.2) — rastgele planlarda `Σ sütun = gerçek` | Format reddi ve puan hatası riski |
| **Bütünleşik** | Küçük örnek (2 TM, 2 talep, 1 gün) → elle hesaplanmış maliyet | Uçtan uca doğruluk |
| **Regresyon** | MVP'nin hayalet rota senaryosu | Aynı hata bir daha geçmesin — `[O, O2, D]` rotasına `O2→D2` talebi bağlanmaya çalışılsın, exception beklensin |
| **Kapı** | Optimizatör maliyeti == simülatör maliyeti | §6. Kuruş farkı = teslim bloke |

**Sağlık testleri** (başarısızlık hata değil, uyarı — ama araştırılır):
- **Tır kısa hatta (<100 km) çıkıyorsa → şüphe.** O aralıkta Kamyon daha ucuz *ve* tır iki slot yakıyor (§4.4)
- Tır çok duraklı rota yapıyorsa → slot muhasebesinde şüphe (§4.1)
- Herhangi bir TM'de tır dokunuşu kapasiteyi aşıyorsa → kısıt sızıntısı (toplam 69 değil, **TM bazında** kontrol — havuzlanamaz, §4.1)
- Konsolidasyon oranı %0 ise → ya model çalışmıyor ya elleçleme cezası yanlış
- **Pazartesi (29.06) planında hiç SLA cezası yoksa → kapasite muhasebesi şüpheli** — §4.2'ye göre pik günde bir miktar ceza yapısal olarak beklenir
- Tır'ın taşıdığı desi ortalama günde ~325.000'i aşıyorsa → slot kısıtı sızdırıyor (§4.1 tavanı)

> **Silinen sağlık testi:** önceki sürümde "Spot Hafif Kamyon çıkıyorsa → maliyet fonksiyonunda şüphe" vardı. **Yanlıştı** — H. Kamyon 5.600–7.200 desi aralığında meşru şekilde kazanıyor (§4.4). Bu test doğru kodu "düzelttirebilirdi"; bir sağlık testinin yanlış olması, olmamasından beterdir.

---

## 11. Yol Haritası

**İlke: her adımın sonunda teslim edilebilir bir şey olsun.** MVP'nin dersi: geç fark edilen hata pahalıdır.

| # | İş | Neden bu sırada |
|---|---|---|
| 1 | **Katman 0** — veri çekirdeği + doğrulama | Her şey buna dayanıyor. Ucuz, risksiz. |
| 2 | **Katman 3 simülatör** — plan okur, maliyet hesaplar | **Optimizatörden ÖNCE.** Puanlayıcı olmadan hiçbir şey ölçülemez; MVP tam da bu yüzden battı. |
| 3 | **Katman 1** — slot bazlı tahmin, WAPE | Katman 2'nin girdisi. Bağımsız ilerleyebilir. |
| 4 | **Greedy taban çizgisi** (§9) — konsolidasyonsuz direkt sefer, tır slot bütçeli | **Çalışan, geçerli, teslim edilebilir çözüm.** MILP'in kıyas zemini ve sigortası. |
| 5 | **Katman 2 MILP** — servis havuzu + set-partitioning | Asıl kazanç. En riskli parça (§5.4 ölçek). Greedy'den **warm start** alır — taban çizgisinden asla kötü olamaz. |
| 6 | **LNS** | Zaman kalırsa. |

Çıktı yazıcısı (§8) 4. adımla birlikte gelir — greedy taban çizgisi teslim edilebilir olacaksa dosyayı da üretmesi gerekir. Test stratejisi (§10) 1. adımdan itibaren paralel yürür, sonda eklenmez.

**2. sıra tartışmaya kapalı.** Simülatör olmadan yazılan optimizatör, MVP'nin tekrarıdır.

**4. sıra sigortadır.** Katman 2 MILP'i ölçek nedeniyle oturmayabilir; greedy taban çizgisi varsa en kötü senaryoda geçerli bir plan teslim edilir — MVP'de olmayan şey buydu.

---

## 12. Risk Matrisi

| Risk | Etki | Olasılık | Azaltma |
|---|---|---|---|
| MILP ölçeği çözülemez | Yüksek | **Yüksek** | Emtia toplulaştırma + olay-güdümlü ızgara + kayan pencere + CP-SAT; greedy taban çizgisi sigorta (§9) |
| Çıktı formatı reddedilir | **Çok yüksek** | **Orta** | Şema §8'de tanımlı; Katman 3 format kapısı + muhasebe invariantı (§8.2) + şablonla birebir kıyas. *Not: v2'de bu risk "düşük" işaretlenmişti — şablon okunmadan verilmiş bir nottu. İki dosyanın tarih/saat formatları farklı ve şablonun kendisi tutarsız (§8.1); dikkat gerektiriyor.* |
| Tır slotu fizibiliteyi kırar (Balıkesir 0, Tekirdağ 0) | Yüksek | Orta | Tır-yasaklı/slotsuz TM'lerde kamyon planı; slot bütçesi sert kısıt |
| Pik gün elleçlemeyi aşar (Pazartesi yapısal — §4.2) | **Yüksek** | **Yüksek** | Bekletme/gün-yayma modelin merkez mekanizması; günlük kapasite Katman 3'te sert kural; pik günde bir miktar SLA cezası bütçelenir |
| Yük-bağımlı süre → optimizatör ≠ simülatör uyuşmazlığı | Yüksek | Orta | Sabit-yük (tam kapasite) varsayımı + post-pass (§5.4); §6 kapısı post-pass çıktısında çalışır |
| Runtime sınırı sonradan sıkı gelir | Orta | Orta | Nihai sınır belirsiz (§3); CP-SAT'ta anytime çözüm, greedy fallback |
| Elleçleme atomikliği modellenmezse tır fazla sevilir | Orta | Orta | §5.2 kuralı; Katman 3 bağımsız doğrular |
| Tır kapasiteleri tekrar güncellenir | Orta | Düşük | Jüri birden çok takıma "güncelleme yapılacaktır" demişti; elimizdeki `tir_kapasiteleri v2.xlsx` bu güncelleme görünüyor (§4.1). Katman 0 Excel'den okur, elle yazılmaz → yeni dosya gelirse kod değişmez |

---

## 13. MVP'den Ne Kalıyor?

| Bileşen | Karar |
|---|---|
| `config.py` | **Kısmen** — sabitler kalır, araç parametreleri Excel'e taşınır |
| `data_loader.py` | Yeniden yazılır (5 yeni şema, talep ID, slot) |
| `layer1_prediction/` | **Uyarlanır** — omurga sağlam, hedef ve feature'lar değişir |
| `layer2_assignment/distance.py` | **Silinir** — Haversine yasak, gerçek km veriliyor |
| `layer2_assignment/rental_placer.py` | **Silinir** — saat bazlı, konsolidasyonlu yeniden kurulur |
| `layer2_assignment/waypoint.py` | **Silinir** — hatalı (§2) ve kavramsal olarak geçersiz |
| `layer2_assignment/spot_assigner.py` | **Silinir** — hat-gün bağımsız greedy varsayımı çöktü; %10 doluluk kuralı da kalktı |
| `layer2_assignment/cost_function.py` | **Yeniden yazılır** — saatlik model; izolasyon ilkesi korunur (iyi karardı) |
| `layer3_validation/ilp_validator.py` | Fikir yaşar, kod gitmez |
| `layer3_validation/invariant.py` | **Genişletilir** — simülatörün içine (§6) |
| `output_writer.py` | Yeniden yazılır (§8 şeması); `Karşılanamayan_Yük.xlsx` üretimi **silinir** (§8.4) |

**Korunacak iyi kararlar:** maliyet fonksiyonu izolasyonu · kanonik yuvarlama · zero-floor · tek global tahmin modeli · WAPE tercihi · invariant fikri (artık simülatör olarak) · **muhasebe kuralı `Σ sütun = gerçek`** (§8.2, MVP'de doğru kurulmuştu).

---

## 14. İş Bölümü (v4'te sabitlendi)

| Kişi | Sorumluluk | Kapsam |
|---|---|---|
| **A** | Katman 0 + Katman 3 | Veri çekirdeği (ilk iş — herkesi açar), sonra bağımsız simülatör + format kapısı + altın test vektörleri |
| **B** | Katman 1 | Slot bazlı tahmin, WAPE, backtest, talep ID, `Talep-tahmini.xlsx` |
| **C** | Greedy + çıktı + entegrasyon | §9 taban çizgisi (öteleme merkez adım), kiralık yerleştirme, `Tasima-plani.xlsx`, `main.py` tek komut |
| **D** | Katman 2 | Servis havuzu, maliyet fonksiyonu (yük-bağımlı süre çözümü), CP-SAT, kayan pencere, warm start, LNS |

Bağımsızlık kuralı: **A, C ve D'nin optimizasyon koduna dokunmaz** (§6 — simülatör optimizatörle kod paylaşmaz). C ile D `Servis` nesnesini ve maliyet fonksiyonunu paylaşır. Ayrıntılı görev listesi GitHub issue'larındadır.

Bunun dışında mimaride jüriye sorulacak açık soru **yok**. v2'de "sorulmalı" diye işaretlenen maliyet dağıtımı, muhasebe invariantından ve MVP precedent'inden türetildi (§8.2).
