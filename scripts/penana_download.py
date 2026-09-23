#!/usr/bin/env python3
"""Download Penana full-story PDF.

Modes:
  --online   Real HTTP GET via requests. Failure => non-zero exit. Never
             copies a local PDF to fake success.
  --offline  Explicit local fallback: copy original PDF into downloads.
             Labeled OFFLINE FALLBACK, not a network download.

Default: --online.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "novel" / "source" / "penana" / "config.json"
OUT_DIR = ROOT / "novel" / "source" / "penana" / "downloads"
LATEST_PATH = OUT_DIR / "penana-latest.pdf"
LOCAL_ORIGINAL = (
    ROOT / "novel" / "source" / "original" / "說好一起當吊車尾-妳神化全開yJS9juj4220.pdf"
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def validate_pdf_bytes(data: bytes) -> tuple[bool, str, int | None]:
    """Return (ok, reason, page_count)."""
    if data[:4] != b"%PDF":
        head = data[:500]
        if b"<html" in head.lower() or b"<!doctype" in head.lower():
            return False, "HTML response (even if HTTP 200) — not a PDF", None
        return False, "first 4 bytes are not %PDF", None
    if b"<html" in data[:512].lower():
        return False, "looks like HTML wrapper", None
    try:
        import pymupdf
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            doc = pymupdf.open(tmp_path)
            pages = doc.page_count
            doc.close()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"PyMuPDF cannot open: {exc}", None
    if pages <= 0:
        return False, "page count is 0", None
    return True, "valid PDF", pages


def offline_fallback() -> int:
    print("MODE: OFFLINE FALLBACK (not a network download)")
    if not LOCAL_ORIGINAL.is_file():
        print(f"Local original missing: {LOCAL_ORIGINAL}", file=sys.stderr)
        return 2
    data = LOCAL_ORIGINAL.read_bytes()
    ok, reason, pages = validate_pdf_bytes(data)
    if not ok:
        print(f"OFFLINE FALLBACK failed: {reason}", file=sys.stderr)
        return 5
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_bytes(data)
    print(f"copied local original -> {LATEST_PATH.relative_to(ROOT).as_posix()}")
    print(f"mode                 : OFFLINE_FALLBACK")
    print(f"size                 : {len(data)}")
    print(f"SHA-256              : {sha256_bytes(data)}")
    print(f"page_count           : {pages}")
    print(f"PDF valid            : True ({reason})")
    return 0


def browser_headers(cfg: dict) -> dict[str, str]:
    # HTTP header values must be latin-1; percent-encode non-ASCII path.
    referer = cfg.get("story_url") or (
        "https://www.penana.com/story/216000/說好一起當吊車尾-妳神化全開"
    )
    from urllib.parse import quote, urlsplit, urlunsplit

    parts = urlsplit(referer)
    ascii_referer = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path, safe="/%"),
            quote(parts.query, safe="=&%[]"),
            quote(parts.fragment, safe=""),
        )
    )
    return {
        "User-Agent": UA,
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": ascii_referer,
    }


def online_download() -> int:
    print("MODE: ONLINE DOWNLOAD")
    try:
        cfg = load_config()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    url = (cfg.get("pdf_url") or "").strip()
    if not url:
        print("pdf_url is empty — online mode refuses to fall back.", file=sys.stderr)
        return 2

    timeout = int(cfg.get("timeout", 30))
    retries = max(1, int(cfg.get("retries", 3)))
    headers = browser_headers(cfg)
    story_url = cfg.get("story_url") or headers.get("Referer", "")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resp = None
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            with requests.Session() as session:
                # Warm session like a browser: load story page first (no login).
                try:
                    warm = session.get(
                        story_url,
                        headers=headers,
                        timeout=timeout,
                        allow_redirects=True,
                    )
                    print(
                        f"session warm-up  : story HTTP {warm.status_code} "
                        f"{warm.headers.get('Content-Type', '?')} "
                        f"cookies={len(session.cookies)}"
                    )
                except requests.RequestException as exc:
                    print(f"session warm-up failed (ignored): {exc}")

                resp = session.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
                print(f"final request URL: {resp.url}")
                print(f"redirect history  : {[ (h.status_code, h.headers.get('Location','')) for h in resp.history ]}")
            break
        except requests.RequestException as exc:
            last_err = str(exc)
            print(f"attempt {attempt}/{retries} failed: {exc}")
    else:
        print(f"All retries failed: {last_err}", file=sys.stderr)
        return 3

    assert resp is not None
    ctype = resp.headers.get("Content-Type", "")
    clen = resp.headers.get("Content-Length", "(missing)")
    body = resp.content
    print(f"HTTP status      : {resp.status_code}")
    print(f"Content-Type     : {ctype}")
    print(f"Content-Length   : {clen}")
    print(f"actual size      : {len(body)}")
    print(f"redirect URL     : {resp.url if resp.url != url else '(none)'}")
    print(f"SHA-256          : {sha256_bytes(body)}")

    if resp.status_code != 200:
        print("PDF valid        : False (non-200)")
        print("preview (500B)   :", repr(body[:500]))
        print("Not saved — existing penana-latest.pdf untouched.")
        return 4

    ok, reason, pages = validate_pdf_bytes(body)
    print(f"PDF valid        : {ok} ({reason})")
    if pages is not None:
        print(f"page_count       : {pages}")
    if not ok:
        print("preview (500B)   :", repr(body[:500]))
        print("Not saved — existing penana-latest.pdf untouched.")
        return 5

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stamped = OUT_DIR / f"penana-download-{stamp}.pdf"
    stamped.write_bytes(body)
    LATEST_PATH.write_bytes(body)
    print(f"mode             : REAL_DOWNLOAD")
    print(f"saved (stamped)  : {stamped.relative_to(ROOT).as_posix()}")
    print(f"saved (latest)   : {LATEST_PATH.relative_to(ROOT).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Penana PDF downloader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--online", action="store_true", help="real HTTP download")
    group.add_argument("--offline", action="store_true", help="copy local original (fallback)")
    args = parser.parse_args(argv)
    if args.online:
        return online_download()
    return offline_fallback()


if __name__ == "__main__":
    sys.exit(main())
