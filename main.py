# -*- coding: utf-8 -*-
"""Tek giris noktasi: veri -> tahmin -> plan -> dogrulama -> cikti.

Juri runtime'i tahmin + planlama toplami olarak oluyor, o yuzden
her asamanin suresi loglanıyor. --fast greedy, --full MILP+LNS (henuz hazir degil).

Kapi basarisizliginda hicbir dosya yazilmaz (gecici klasor kullanilir,
kapılar gecerse kopyalanir).
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

import config
from katman0_veri import veriyi_yukle
from katman1_tahmin import tahmin_uret, talep_id_ata, talep_tahmini_yaz
from katman2_planlama import plan_uret, plan_uret_full
from katman3_simulator import dogrula_ve_yaz
from katman3_simulator.simulator import SimulasyonHatasi


def _determinizm_icin_yeniden_baslat_gerekiyorsa() -> None:
    """Determinizm (proje kuralı: teslim edilen dosyalar her koşuda bit düzeyinde aynı
    olmalı, bkz. config.SEED). Python'ın string/set hash'i PYTHONHASHSEED'e göre HER
    SÜREÇTE rastgele salınır (varsayılan); bu, `set`/`dict`-anahtarlı iç yapılar
    üzerinden CP-SAT'a giden model kurulumunu (ve dolayısıyla MILP çözücüsünün süre
    sınırına takıldığı — yani kanıtlanmış optimal olmayan — durumlarda bulduğu çözümü)
    koşudan koşuya değiştirebiliyor; canlı testle ölçülüp doğrulandı (issue #21).
    Hash seed yalnızca yorumlayıcı BAŞLARKEN sabitlenebildiği için, ayarlı değilse
    süreç aynı ortam değişkeniyle kendini yeniden başlatır. `subprocess.run` (stdout/
    stderr doğrudan miras alınır) kullanılıyor — `os.execv` Windows'ta süreç yer
    değiştirmesini bazı terminal/boru hattı kurulumlarında güvenilir aktarmıyor.
    `--seed` argümanı (`_seed_ayarla`) yalnız `random`/`numpy`'ı tohumlar; CP-SAT'ın
    dolaylı olarak dayandığı Python hash tohumunu KAPSAMAZ, o yüzden bu koruma ayrıca
    gerekli.
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        sonuc = subprocess.run([sys.executable] + sys.argv, env=env)
        sys.exit(sonuc.returncode)


def _seed_ayarla(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def _args_parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AYZEK 3.2 - Lojistik Optimizasyon")
    p.add_argument("--fast", action="store_true", help="Greedy mod (varsayilan)")
    p.add_argument(
        "--full", action="store_true",
        help="MILP kayan pencere (+ --lns-minutes ile LNS). Her pencerede greedy "
             "ile kiyaslanir, kotuyse greedy'ye duser.",
    )
    p.add_argument(
        "--milp-minutes", type=float, default=10.0, metavar="N",
        help="MILP zaman butcesi dakika (--full ile, varsayilan 10)",
    )
    p.add_argument(
        "--lns-minutes", type=float, default=0.0, metavar="N",
        help="LNS yik-onar turu butcesi dakika (--full ile, varsayilan 0 = kapali)",
    )
    p.add_argument(
        "--seed", type=int, default=config.SEED,
        help=f"Determinizm icin seed (varsayilan {config.SEED})",
    )
    p.add_argument(
        "--output-dir", type=str, default=str(config.CIKTI_KLASORU),
        help="Cikti klasoru (varsayilan cikti/)",
    )
    return p.parse_args()


def main() -> None:
    args = _args_parse()
    _seed_ayarla(args.seed)
    cikti_dir = Path(args.output_dir)

    t0 = time.perf_counter()

    try:
        veri = veriyi_yukle()
        t1 = time.perf_counter()

        tahmin_raw = tahmin_uret(veri)
        tahmin = talep_id_ata(tahmin_raw)
        t2 = time.perf_counter()

        # Dosyalari once gecici klasore yaz; kapılar gecmeden cikti/ klasorune tasinmaz.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_talep = str(Path(tmp) / "Talep-tahmini.xlsx")
            tahmin_xlsx = talep_tahmini_yaz(tahmin, tmp_talep)

            if args.full:
                tmp_plan = plan_uret_full(
                    veri, tahmin, cikti_dizini=tmp,
                    milp_dakika=args.milp_minutes,
                    lns_dakika=args.lns_minutes,
                )
            else:
                tmp_plan = plan_uret(veri, tahmin, cikti_dizini=tmp)
            t3 = time.perf_counter()

            dogrula_ve_yaz(veri, tahmin_xlsx, tmp_plan)
            t4 = time.perf_counter()

            # Kapılar gecti — kalici konuma kopyala
            cikti_dir.mkdir(parents=True, exist_ok=True)
            talep_yolu = str(cikti_dir / "Talep-tahmini.xlsx")
            plan_yolu = str(cikti_dir / "Tasima-plani.xlsx")
            shutil.copy2(tmp_talep, talep_yolu)
            shutil.copy2(tmp_plan, plan_yolu)

    except SimulasyonHatasi as e:
        print(f"\nKAPI HATASI - dosya yazilmadi:\n{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nHATA: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print(f"veri yukleme : {t1 - t0:6.1f} sn")
    print(f"tahmin       : {t2 - t1:6.1f} sn")
    print(f"planlama     : {t3 - t2:6.1f} sn")
    print(f"dogrulama    : {t4 - t3:6.1f} sn")
    print(f"TOPLAM       : {t4 - t0:6.1f} sn")
    print(f"\nCiktilar ({args.output_dir}/):")
    print(f"  {talep_yolu}")
    print(f"  {plan_yolu}")


if __name__ == "__main__":
    _determinizm_icin_yeniden_baslat_gerekiyorsa()
    main()
