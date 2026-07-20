# -*- coding: utf-8 -*-
"""Tek giriş noktası: veri -> tahmin -> plan -> doğrulama -> çıktı.

Jüri runtime'ı tahmin + planlama toplamı olarak ölçüyor, o yüzden
her aşamanın süresi baştan beri loglanıyor. Şimdilik iskelet;
katmanlar doldukça bu akışın kendisi değişmeyecek.
"""
import time

from katman0_veri import veriyi_yukle
from katman1_tahmin import tahmin_uret
from katman2_planlama import plan_uret
from katman3_simulator import dogrula_ve_yaz


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
    main()
