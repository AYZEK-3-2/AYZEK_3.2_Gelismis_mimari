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
veri yukleme :    0.8 sn
tahmin       :   19.8 sn
planlama     :    6.8 sn
dogrulama    :   97.5 sn
TOPLAM       :  124.8 sn
```

Ek seçenekler:

```bash
python main.py --output-dir sonuclar/   # farkli cikti klasoru
python main.py --seed 123               # farkli seed (varsayilan 42)
python main.py --full                   # MILP+LNS (henuz hazir degil, greedy calisir)
python main.py --milp-minutes 5         # MILP sure butcesi (--full ile)
```

Deterministik: aynı seed ile iki koşu bit düzeyinde aynı dosyaları üretir.

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
