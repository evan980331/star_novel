#!/usr/bin/env python3
"""Sync pipeline: online download → validate/hash → compare manifest → parse.

Flow:
  Penana URL → HTTP download → PDF validation → SHA-256 →
  compare with manifest → same: No changes detected.
  → different: keep new PDF → PyMuPDF → TXT → chapter parser → manifest

No offline fallback in sync (phase 2). No bulk scraping / login / CAPTCHA bypass.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run(args: list[str]) -> int:
    label = " ".join(args)
    print(f"\n=== {label} ===")
    proc = subprocess.run([sys.executable, *args], cwd=str(ROOT))
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Novel sync pipeline")
    parser.add_argument(
        "--mode",
        choices=("online", "offline"),
        default="online",
        help="download mode (default: online)",
    )
    args = parser.parse_args()

    code_dl = run([str(SCRIPTS / "penana_download.py"), f"--{args.mode}"])
    if code_dl != 0:
        print(f"download failed (exit {code_dl}); aborting sync.", file=sys.stderr)
        return code_dl

    code_parse = run([str(SCRIPTS / "parse_novel.py")])
    return code_parse


if __name__ == "__main__":
    sys.exit(main())
