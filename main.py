# -*- coding: utf-8 -*-
"""Tek giriş noktası: veri -> tahmin -> plan -> doğrulama -> çıktı.

Jüri runtime'ı tahmin + planlama toplamı olarak ölçüyor, o yüzden
her aşamanın süresi baştan beri loglanıyor. Şimdilik iskelet;
katmanlar doldukça bu akışın kendisi değişmeyecek.
"""
import os
import subprocess
import sys
import time

from katman0_veri import veriyi_yukle
from katman1_tahmin import tahmin_uret
from katman2_planlama import plan_uret
from katman3_simulator import dogrula_ve_yaz


def _determinizm_icin_yeniden_baslat_gerekiyorsa():
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
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        sonuc = subprocess.run([sys.executable] + sys.argv, env=env)
        sys.exit(sonuc.returncode)


def main():
    t0 = time.perf_counter()
    veri = veriyi_yukle()
    t1 = time.perf_counter()

    tahmin = tahmin_uret(veri)
    t2 = time.perf_counter()

    plan = plan_uret(veri, tahmin)
    t3 = time.perf_counter()

    dogrula_ve_yaz(veri, tahmin, plan)
    t4 = time.perf_counter()

    print()
    print(f"veri yükleme : {t1 - t0:6.1f} sn")
    print(f"tahmin       : {t2 - t1:6.1f} sn")
    print(f"planlama     : {t3 - t2:6.1f} sn")
    print(f"doğrulama    : {t4 - t3:6.1f} sn")
    print(f"TOPLAM       : {t4 - t0:6.1f} sn")


if __name__ == "__main__":
    _determinizm_icin_yeniden_baslat_gerekiyorsa()
    main()
