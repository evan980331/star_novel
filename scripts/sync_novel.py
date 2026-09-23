#!/usr/bin/env python3
"""Sync pipeline: download → hash/compare → parse → chapters → manifest.

Phase 1 only chains local steps. Future: latest-chapter detection, HTML
metadata, public API, automatic PDF URL refresh. No bulk scraping.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run(name: str) -> int:
    print(f"\n=== {name} ===")
    proc = subprocess.run([sys.executable, str(SCRIPTS / name)], cwd=str(ROOT))
    return proc.returncode


def main() -> int:
    codes = [
        run("penana_download.py"),
        run("parse_novel.py"),
    ]
    # download may exit 2 (empty pdf_url) — still attempt parse if PDF exists
    if codes[1] != 0 and codes[0] in (0, 2):
        return codes[1]
    if any(c not in (0, 2) for c in codes):
        return 1
    return codes[1] if codes[1] not in (0, 2) else 0


if __name__ == "__main__":
    sys.exit(main())
