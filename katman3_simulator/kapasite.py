from collections import defaultdict


class KapasiteDefter:
    """TM-gün bazında elleçleme ve tır slotu takip eder."""

    def __init__(self, ellecleme_kapasiteleri: dict, tir_kapasiteleri: dict):
        self.ellecleme_kap = ellecleme_kapasiteleri
        self.tir_kap = tir_kapasiteleri

        # (tm, gun) -> toplam elleçlenen desi
        self.ellecleme_kullanim = defaultdict(float)

        # (tm, gun) -> toplam tır dokunuş sayısı
        self.tir_kullanim = defaultdict(int)

    def ellecleme_ekle(self, tm: str, gun: str, desi: float) -> None:
        """Bir TM'de bir gün için elleçleme kaydı ekler."""
        self.ellecleme_kullanim[(tm, gun)] += desi

    def tir_dokunusu_ekle(self, tm: str, gun: str) -> None:
        """Bir TM'de bir gün için tır dokunuşu kaydı ekler."""
        self.tir_kullanim[(tm, gun)] += 1

    def dogrula(self) -> list:
        """Tüm kayıtları kontrol eder, ihlalleri listeler."""
        ihlaller = []

        # Elleçleme kapasitesi kontrolü
        for (tm, gun), kullanim in self.ellecleme_kullanim.items():
            kapasite = self.ellecleme_kap[tm]
            if kullanim > kapasite:
                ihlaller.append(
                    f"Elleçleme aşımı: {tm} {gun} -> "
                    f"{kullanim:.0f} / {kapasite:.0f} desi"
                )

        # Tır slot kontrolü
        for (tm, gun), kullanim in self.tir_kullanim.items():
            kapasite = self.tir_kap[tm]
            if kullanim > kapasite:
                ihlaller.append(
                    f"Tır slot aşımı: {tm} {gun} -> "
                    f"{kullanim} / {kapasite} slot"
                )

        return ihlaller