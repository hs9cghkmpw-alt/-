#!/usr/bin/env python3
"""Brain Twin 2.0 CLI エントリポイント。

使い方:
    python brain.py add "今日はBrain Twinの設計について考えた"
    python brain.py process
    python brain.py search "Brain Twin"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_twin.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
