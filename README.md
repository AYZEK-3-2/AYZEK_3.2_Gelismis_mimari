# AYZEK 3.2 — Gelişmiş Çözüm Aşaması

TEKNOFEST 2026 · Hepsiburada Lojistik Optimizasyonu — Gelişmiş aşama çözümü.

## Mimari

Tek kaynak: [docs/GELISMIS_Sistem_Mimarisi_v4.md](docs/GELISMIS_Sistem_Mimarisi_v4.md) (Word kopyası aynı klasörde).

Dört katman:

| Katman | İş | Sahibi |
|---|---|---|
| 0 | Veri & kısıt çekirdeği (immutable, doğrulanmış) | A |
| 1 | Talep tahmini — slot bazlı LightGBM, WAPE | B |
| 2 | Servis ağı tasarımı — servis havuzu + CP-SAT + LNS (sigorta: greedy taban çizgisi) | C + D |
| 3 | Bağımsız simülatör + kalite/format kapısı | A |

Taşıyıcı kurallar: servis birinci sınıf nesnedir; simülatör optimizatörle **hiçbir kod paylaşmaz**; simülatör-optimizatör maliyetleri kuruşu kuruşuna uyuşmadan teslim yok.

## Veri

`veri/` altında yarışma veri setleri (66.024 talep · 289 hat · 18 TM), `veri/sablon/` altında jüri çıktı şablonları, `veri/dokuman/` altında şartname ve soru-cevap PDF'leri.

## Kurulum

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

Kurulum doğrulaması:

```bash
pytest
```

Tüm testler yeşil geçmeli.

## Çalıştırma

```bash
python main.py
```

Tek komutla iki teslim dosyası üretilir: `cikti/Tasima-plani.xlsx` ve `cikti/Talep-tahmini.xlsx`.
Kalite kapıları geçilmeden hiçbir dosya yazılmaz; hata durumunda sıfır olmayan exit code döner.

Süre logu her koşuda stdout'a yazılır (tipik):

```
veri yukleme :    0.7 sn
tahmin       :    5.8 sn
planlama     :    2.3 sn
dogrulama    :   16.4 sn
TOPLAM       :   25.2 sn
```

Ek seçenekler:

```bash
python main.py --output-dir sonuclar/   # farkli cikti klasoru
python main.py --seed 123               # farkli seed (varsayilan 42)
python main.py --full --milp-minutes 5  # MILP kayan pencere (asagiya bakin)
python main.py --full --lns-minutes 2   # + LNS yik-onar turu
```

Deterministik: aynı seed ile iki koşu **içerik olarak** birebir aynı iki dosya
üretir. (Bayt düzeyinde değil — `.xlsx` bir zip'tir ve içinde oluşturma zaman
damgası taşır; dosyaları `md5` ile değil, okuyup karşılaştırarak doğrulayın.)

### `--full` (MILP kayan pencere) — durum

`--full` bağlıdır ve çalışır: her 3 günlük pencerede CP-SAT modeli kurulur,
sonucu greedy taban çizgisinin **gerçek** maliyetiyle kıyaslanır ve ucuz olan
commit edilir; MILP çözüm bulamazsa o pencere greedy'ye düşer. Bu yüzden
`--full` hiçbir koşulda greedy'den kötü bir plan üretemez.

**Ama şu an gerçek veride kazanç getirmiyor:** CP-SAT ayrılan sürede hiçbir
pencerede fizibil çözüm bulamıyor (pencere başına ~2,3M tam sayı değişken), yani
tüm pencereler greedy'ye düşüyor — sonuç `--fast` ile aynı plan, çok daha uzun
sürede. Teslim için **varsayılan (greedy) mod kullanılmalıdır.**

Kalan iş, aday havuzunu küçültmektir (3 günlük pencerede 9.918 aday); ayrıntılı
ölçüm ve öneriler: [docs/INCELEME_NOTU.md](docs/INCELEME_NOTU.md).

Klasör düzeni:

```
katman0_veri/       veri ve kısıt çekirdeği
katman1_tahmin/     talep tahmini (LightGBM, WAPE)
katman2_planlama/   greedy + CP-SAT planlama
katman3_simulator/  bağımsız simülatör ve kalite kapıları
tests/              pytest
cikti/              üretilen teslim dosyaları (git dışı)
```

## İş takibi

Görevler GitHub Issues'ta; pano: [AYZEK-3-2 org Project #1](https://github.com/orgs/AYZEK-3-2/projects/1).
