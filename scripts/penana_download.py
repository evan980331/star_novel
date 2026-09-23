#!/usr/bin/env python3
"""Download Penana full-story PDF from config.json (single GET, no scraping loops)."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "novel" / "source" / "penana" / "config.json"
OUT_DIR = ROOT / "novel" / "source" / "penana" / "downloads"
OUT_PATH = OUT_DIR / "penana-latest.pdf"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download() -> int:
    if not CONFIG_PATH.is_file():
        print(f"Missing config: {CONFIG_PATH}", file=sys.stderr)
        return 1
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    url = (cfg.get("pdf_url") or "").strip()
    if not url:
        # Offline fallback so parse/sync remain testable until pdf_url is set.
        local = ROOT / "novel" / "source" / "original" / "說好一起當吊車尾-妳神化全開yJS9juj4220.pdf"
        if local.is_file():
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            data = local.read_bytes()
            if data[:4] != b"%PDF":
                print("Local original is not a PDF; refusing to copy.")
                return 5
            OUT_PATH.write_bytes(data)
            print("pdf_url is empty in config.json — no network download performed.")
            print(f"Offline fallback (NOT a download): copied {local.relative_to(ROOT).as_posix()}")
            print(f"Content-Type     : (local file)")
            print(f"actual size      : {len(data)}")
            print(f"SHA-256          : {sha256_bytes(data)}")
            print("PDF valid        : True")
            print(f"saved            : {OUT_PATH.relative_to(ROOT).as_posix()}")
            return 0
        print("pdf_url is empty in config.json — set a complete Penana PDF URL first.")
        print("No download performed.")
        return 2

    timeout = int(cfg.get("timeout", 30))
    retries = int(cfg.get("retries", 3))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            break
        except requests.RequestException as exc:
            last_err = str(exc)
            print(f"attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(1.5 * attempt)
    else:
        print(f"All retries failed: {last_err}", file=sys.stderr)
        return 3

    ctype = resp.headers.get("Content-Type", "")
    clen = resp.headers.get("Content-Length", "?")
    body = resp.content
    print(f"HTTP status      : {resp.status_code}")
    print(f"Content-Type     : {ctype}")
    print(f"Content-Length   : {clen}")
    print(f"actual size      : {len(body)}")
    print(f"SHA-256          : {sha256_bytes(body)}")

    if resp.status_code != 200:
        print("PDF valid        : False (non-200)")
        print("Not saved.")
        return 4

    is_pdf = body[:4] == b"%PDF"
    looks_html = b"<html" in body[:512].lower() or "html" in ctype.lower()
    print(f"PDF valid        : {is_pdf}")

    if not is_pdf or looks_html:
        print("Response looks like HTML/error — refusing to save as PDF.")
        preview = body[:200].decode("utf-8", errors="replace")
        print(f"preview: {preview!r}")
        return 5

    OUT_PATH.write_bytes(body)
    print(f"saved            : {OUT_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(download())
