# -*- coding: utf-8 -*-
"""Tahmin backtest'ini tek komutla çalıştırır: python scripts/backtest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from katman1_tahmin.model import main

if __name__ == "__main__":
    main()
