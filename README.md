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

## Kurulum (Windows)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Doğrulama: `pytest` (iskelet testleri yeşil olmalı).

## Çalıştırma

```powershell
python main.py
```

Tek komut, iki teslim dosyası: `Tasima-plani.xlsx` ve `Talep-tahmini.xlsx` (deterministik, sabit seed). Akış iskeleti hazır; katmanlar issue'lar kapandıkça doluyor. Klasör düzeni:

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
