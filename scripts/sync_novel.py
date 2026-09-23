#!/usr/bin/env python3
"""Sync pipeline with chapter-range management and temp-PDF cleanup.

Flow:
  1 read config
  2 inspect local manifest + chapters
  3 determine existing chapter range
  4 determine required remote range
  5 if already complete → exit success without downloading
  6 otherwise download required PDF
  7 validate PDF (inside downloader)
  8 SHA-256 (inside parser)
  9 parse
  10 verify expected chapter range
  11 update manifest
  12 remove temporary PDF (only under novel/source/penana/)
  13 report result

No incremental Penana API yet (loadingfile.php still 302 → home.php).
No bulk scraping / login / CAPTCHA bypass.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIG_PATH = ROOT / "novel" / "source" / "penana" / "config.json"
MANIFEST_PATH = ROOT / "novel" / "source" / "penana" / "manifest.json"
CHAPTERS_DIR = ROOT / "novel" / "chapters"
PENANA_DIR = ROOT / "novel" / "source" / "penana"
DOWNLOADS_DIR = PENANA_DIR / "downloads"
TEMP_PDF = DOWNLOADS_DIR / "penana-latest.pdf"
CHAPTER_FILE = re.compile(r"^(\d{3})\.md$")


def load_json(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def scan_chapter_range(chapters_dir: Path | None = None) -> tuple[int, int, int] | None:
    d = chapters_dir or CHAPTERS_DIR
    if not d.is_dir():
        return None
    nums: list[int] = []
    for p in d.iterdir():
        if p.is_file():
            m = CHAPTER_FILE.match(p.name)
            if m:
                nums.append(int(m.group(1)))
    if not nums:
        return None
    return min(nums), max(nums), len(nums)


def required_range(cfg: dict, override_start: int | None, override_end: int | None) -> tuple[int, int]:
    start = override_start if override_start is not None else int(cfg.get("requested_start", 0))
    end = override_end if override_end is not None else int(cfg.get("requested_end", 59))
    return start, end


def existing_range(man: dict, scanned: tuple[int, int, int] | None) -> tuple[int, int, int] | None:
    """Prefer manifest range when consistent with disk; else disk scan."""
    if scanned is None:
        return None
    m_start = man.get("downloaded_start")
    m_end = man.get("downloaded_end")
    if isinstance(m_start, int) and isinstance(m_end, int):
        # Trust disk files as ground truth for what is present.
        return scanned
    return scanned


def covers(existing: tuple[int, int, int] | None, req_start: int, req_end: int) -> bool:
    if existing is None:
        return False
    start, end, count = existing
    if count <= 0:
        return False
    if start > req_start or end < req_end:
        return False
    # No gaps: count must match inclusive span (parser emits contiguous NNN.md).
    expected = end - start + 1
    return count == expected and start <= req_start and end >= req_end


def fmt_range(t: tuple[int, int] | tuple[int, int, int]) -> str:
    return f"{t[0]}-{t[1]}"


def safe_remove_temp_pdf(path: Path) -> bool:
    """Delete only pipeline temp PDFs under novel/source/penana/."""
    try:
        resolved = path.resolve()
    except OSError:
        return False

    penana_root = PENANA_DIR.resolve()
    downloads_root = DOWNLOADS_DIR.resolve()
    original_root = (ROOT / "novel" / "source" / "original").resolve()
    backup_root = (ROOT / "novel" / "source" / "backup").resolve()

    # Never touch original/ or backup/ user data.
    if original_root in resolved.parents or resolved == original_root:
        print(f"REFUSE delete (original): {resolved}")
        return False
    if backup_root in resolved.parents or resolved == backup_root:
        print(f"REFUSE delete (backup): {resolved}")
        return False
    if downloads_root not in resolved.parents and resolved != downloads_root:
        # Must live under penana/ (preferably downloads/)
        if penana_root not in resolved.parents and resolved != penana_root:
            print(f"REFUSE delete (outside penana): {resolved}")
            return False
        if resolved.suffix.lower() != ".pdf":
            print(f"REFUSE delete (not pdf): {resolved}")
            return False
    if not resolved.is_file():
        return False
    if resolved.suffix.lower() != ".pdf":
        print(f"REFUSE delete (not .pdf): {resolved}")
        return False

    resolved.unlink()
    print(f"removed temp PDF  : {path.relative_to(ROOT).as_posix()}")
    return True


def update_manifest_after_cleanup(start: int, end: int, count: int) -> None:
    man = load_json(MANIFEST_PATH)
    if not man:
        return
    man["pdf_removed"] = True
    man["temp_pdf"] = "removed"
    man["downloaded_start"] = start
    man["downloaded_end"] = end
    man["downloaded_chapter_count"] = count
    if man.get("parser_result") == "ok" and count > 0:
        man["status"] = "complete"
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"manifest updated  : pdf_removed=true, range={start}-{end}, "
        f"chapters={count}, status={man.get('status')}"
    )


def run(args: list[str]) -> int:
    label = " ".join(Path(a).name if a.endswith(".py") else a for a in args)
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
    parser.add_argument("--request-start", type=int, default=None, help="override required start (tests)")
    parser.add_argument("--request-end", type=int, default=None, help="override required end (tests)")
    parser.add_argument("--dry-run", action="store_true", help="range check only, no download/parse")
    parser.add_argument("--force", action="store_true", help="download even if already up to date")
    parser.add_argument(
        "--keep-pdf",
        action="store_true",
        help="do not delete temp PDF after successful parse",
    )
    parser.add_argument(
        "--simulate-parse-error",
        action="store_true",
        help="force parser step to fail (test: PDF must remain)",
    )
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH)
    man = load_json(MANIFEST_PATH)
    scanned = scan_chapter_range()
    existing = existing_range(man, scanned)
    req_start, req_end = required_range(cfg, args.request_start, args.request_end)
    req = (req_start, req_end)
    parser_ok = man.get("parser_result") == "ok"
    manifest_complete = man.get("status") == "complete"

    print(f"config           : story_id={cfg.get('story_id')} source={cfg.get('source', 'penana')}")
    print(f"required range   : {req_start}-{req_end}")
    if existing:
        print(
            f"existing range   : {existing[0]}-{existing[1]} ({existing[2]} files), "
            f"manifest_status={man.get('status', '(none)')} parser={man.get('parser_result', '(none)')}"
        )
    else:
        print("existing range   : (none)")

    is_complete = (
        covers(existing, req_start, req_end)
        and parser_ok
        and (manifest_complete or (existing is not None and parser_ok))
    )
    # Prefer explicit cover check on disk + ok parser.
    is_complete = covers(existing, req_start, req_end) and parser_ok

    if is_complete and not args.force:
        print(f"Already up to date: chapters {existing[0]}-{existing[1]}")
        print("No download required.")
        if args.dry_run:
            print("dry-run: range check only.")
        return 0

    if is_complete and args.force:
        print("Force update requested despite complete local range.")

    if existing and covers(existing, req_start, req_end) is False:
        if existing[1] < req_end or existing[0] > req_start:
            print(f"Update required: local {fmt_range(existing)} vs required {req_start}-{req_end}")
        else:
            print(f"Update required: local range incomplete vs required {req_start}-{req_end}")
    elif not existing:
        print(f"Update required: no local chapters; required {req_start}-{req_end}")

    if not (existing and covers(existing, req_start, req_end)) or args.force:
        print(f"Need download for range {req_start}-{req_end}.")
    elif args.force:
        print(f"Need re-download for range {req_start}-{req_end}.")

    if args.dry_run:
        if is_complete and not args.force:
            print("dry-run: already complete.")
            return 0
        print("Update required (dry-run): no download performed.")
        return 0

    # --- download ---
    code_dl = run([str(SCRIPTS / "penana_download.py"), f"--{args.mode}"])
    if code_dl != 0:
        print(f"download failed (exit {code_dl}); aborting sync; PDF untouched/kept.", file=sys.stderr)
        return code_dl

    # --- parse (optional simulated failure for tests) ---
    if args.simulate_parse_error:
        print("\n=== parse_novel.py (SIMULATED ERROR) ===")
        print("parser error: simulated failure; keeping PDF for debugging.", file=sys.stderr)
        # Mark manifest parser error without wiping chapters.
        man = load_json(MANIFEST_PATH)
        if man:
            man["parser_result"] = "error"
            man["pdf_removed"] = not TEMP_PDF.is_file()
            MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        elif MANIFEST_PATH.is_file() is False and TEMP_PDF.is_file():
            # minimal error marker when no prior manifest
            MANIFEST_PATH.write_text(
                json.dumps(
                    {"parser_result": "error", "pdf_removed": False},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        print(f"PDF retained      : {'yes' if TEMP_PDF.is_file() else 'no'} (parse failed)")
        return 1

    code_parse = run([str(SCRIPTS / "parse_novel.py")])
    if code_parse != 0:
        print(f"parse failed (exit {code_parse}); keeping PDF.", file=sys.stderr)
        return code_parse

    # --- verify expected chapter range ---
    scanned_after = scan_chapter_range()
    man_after = load_json(MANIFEST_PATH)
    if scanned_after is None:
        print("verify failed: no chapters on disk; keeping PDF.", file=sys.stderr)
        return 1
    if not covers(scanned_after, req_start, req_end):
        print(
            f"verify failed: chapters {fmt_range(scanned_after)} "
            f"do not cover required {req_start}-{req_end}; keeping PDF.",
            file=sys.stderr,
        )
        return 1
    if man_after.get("parser_result") != "ok":
        print("verify failed: manifest parser_result != ok; keeping PDF.", file=sys.stderr)
        return 1
    if man_after.get("sha256") in (None, ""):
        print("verify failed: SHA-256 missing in manifest; keeping PDF.", file=sys.stderr)
        return 1
    if not (man_after.get("page_count") or 0) > 0:
        print("verify failed: page_count missing; keeping PDF.", file=sys.stderr)
        return 1

    print(
        f"verified          : chapters {fmt_range(scanned_after)} "
        f"cover {req_start}-{req_end}, sha256={man_after['sha256'][:16]}..., "
        f"pages={man_after['page_count']}"
    )

    # --- cleanup temp PDF ---
    if args.keep_pdf:
        print("temp PDF kept     : --keep-pdf")
        return 0

    removed = safe_remove_temp_pdf(TEMP_PDF)
    if not removed:
        print("warning: temp PDF not removed (missing or refused).", file=sys.stderr)
        return 0

    update_manifest_after_cleanup(scanned_after[0], scanned_after[1], scanned_after[2])
    print("Sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
