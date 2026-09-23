#!/usr/bin/env python3
"""Tests for range management, duplicate-download prevention, PDF cleanup.

Run: python scripts/test_sync_pipeline.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIG_PATH = ROOT / "novel" / "source" / "penana" / "config.json"
MANIFEST_PATH = ROOT / "novel" / "source" / "penana" / "manifest.json"
CHAPTERS_DIR = ROOT / "novel" / "chapters"
DOWNLOADS_DIR = ROOT / "novel" / "source" / "penana" / "downloads"
TEMP_PDF = DOWNLOADS_DIR / "penana-latest.pdf"
LOCAL_ORIGINAL = (
    ROOT / "novel" / "source" / "original" / "說好一起當吊車尾-妳神化全開yJS9juj4220.pdf"
)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"PASS: {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"FAIL: {name}" + (f" — {detail}" if detail else ""))


def run_sync(*extra: str, mode: str = "offline") -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPTS / "sync_novel.py"), "--mode", mode, *extra]
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")


def chapter_count() -> int:
    if not CHAPTERS_DIR.is_dir():
        return 0
    return sum(1 for p in CHAPTERS_DIR.glob("[0-9][0-9][0-9].md"))


def ensure_baseline_manifest() -> dict:
    """Ensure manifest describes complete 0-59 from current chapters."""
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else {}
    if chapter_count() != 60:
        # rebuild via offline parse if needed
        if not TEMP_PDF.is_file() and LOCAL_ORIGINAL.is_file():
            subprocess.run(
                [sys.executable, str(SCRIPTS / "penana_download.py"), "--offline"],
                cwd=str(ROOT),
                check=True,
                capture_output=True,
            )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_novel.py")],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        )
        man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Normalize range fields for baseline.
    man.setdefault("story_id", "216000")
    man["source"] = "penana"
    man["downloaded_start"] = 0
    man["downloaded_end"] = 59
    man["downloaded_chapter_count"] = 60
    man["requested_start"] = 0
    man["requested_end"] = 59
    man["parser_result"] = man.get("parser_result", "ok") or "ok"
    man["status"] = "complete"
    man["chapter_count"] = man.get("chapter_count", 60)
    man["page_count"] = man.get("page_count", 124)
    man.setdefault(
        "sha256",
        "92778830a1a561513ed61a05773b4f75e8ebdce45494be70c3d188badc3d99d4",
    )
    man.setdefault("source_url", "https://www.penana.com/story/216000/說好一起當吊車尾-妳神化全開")
    man.setdefault("download_url", "")
    man["pdf_removed"] = not TEMP_PDF.is_file()
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return man


def test_a_already_up_to_date() -> None:
    print("\n--- Test A: existing 0..59, sync again → no download, no parse ---")
    ensure_baseline_manifest()
    if TEMP_PDF.is_file():
        TEMP_PDF.unlink()

    # snapshot chapters mtimes
    before = {p.name: p.stat().st_mtime_ns for p in CHAPTERS_DIR.glob("*.md")}
    man_before = MANIFEST_PATH.read_text(encoding="utf-8")

    proc = run_sync()
    out = (proc.stdout or "") + (proc.stderr or "")
    check("A exit 0", proc.returncode == 0, f"rc={proc.returncode}")
    check(
        "A already up to date message",
        "Already up to date: chapters 0-59" in proc.stdout,
        proc.stdout[-300:].replace("\n", " | "),
    )
    check("A no download required", "No download required." in proc.stdout)
    check("A did not run offline copy", "OFFLINE FALLBACK" not in proc.stdout)
    check("A did not reparse", "TXT written" not in proc.stdout)
    check("A no temp pdf created", not TEMP_PDF.is_file())
    after = {p.name: p.stat().st_mtime_ns for p in CHAPTERS_DIR.glob("*.md")}
    check("A chapters unchanged", before == after)
    check("A manifest unchanged", man_before == MANIFEST_PATH.read_text(encoding="utf-8"))


def test_b_update_required_dry_run() -> None:
    print("\n--- Test B: existing 0..59, requested 0..63 → update required ---")
    ensure_baseline_manifest()
    if TEMP_PDF.is_file():
        TEMP_PDF.unlink()

    proc = run_sync("--request-end", "63", "--dry-run")
    out = proc.stdout + proc.stderr
    check("B exit 0 dry-run", proc.returncode == 0, f"rc={proc.returncode}")
    check(
        "B detects update required",
        "Update required" in proc.stdout or "Need download" in proc.stdout,
        proc.stdout.replace("\n", " | "),
    )
    check("B dry-run no download", "no download performed" in proc.stdout.lower() or "dry-run" in proc.stdout.lower())
    check("B did not say up to date for 63", "Already up to date: chapters 0-59" not in proc.stdout)
    check("B no offline fallback", "OFFLINE FALLBACK" not in proc.stdout)
    check("B no temp pdf", not TEMP_PDF.is_file())

    # config must still be 0..59 (do not change known full range)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    check("B config still 0-59", cfg.get("requested_start") == 0 and cfg.get("requested_end") == 59)


def test_c_parse_failure_keeps_pdf() -> None:
    print("\n--- Test C: simulate parser failure → PDF kept ---")
    ensure_baseline_manifest()
    if not LOCAL_ORIGINAL.is_file():
        check("C local original exists", False)
        return

    # Force re-download path
    proc = run_sync("--force", "--simulate-parse-error")
    out = proc.stdout + proc.stderr
    check("C exit != 0", proc.returncode != 0, f"rc={proc.returncode}")
    check("C used offline fallback", "OFFLINE FALLBACK" in proc.stdout)
    check("C pdf exists", TEMP_PDF.is_file())
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    check("C parser_result error", man.get("parser_result") == "error", str(man.get("parser_result")))
    check("C pdf_removed not true", man.get("pdf_removed") is not True)
    # original untouched
    check("C original pdf still exists", LOCAL_ORIGINAL.is_file())

    # restore ok parser_result for later tests via re-parse
    if TEMP_PDF.is_file():
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_novel.py")],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        )
    ensure_baseline_manifest()


def test_d_success_cleans_pdf() -> None:
    print("\n--- Test D: successful parse → PDF deleted, manifest+chapters kept ---")
    ensure_baseline_manifest()
    # Ensure PDF present for cleanup test
    if not TEMP_PDF.is_file():
        subprocess.run(
            [sys.executable, str(SCRIPTS / "penana_download.py"), "--offline"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        )
    check("D pdf before", TEMP_PDF.is_file())
    chapters_before = chapter_count()

    # force full pipeline with cleanup
    proc = run_sync("--force")
    out = proc.stdout + proc.stderr
    check("D exit 0", proc.returncode == 0, f"rc={proc.returncode}\n{out[-500:]}")
    check("D pdf removed", not TEMP_PDF.is_file())
    man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    check("D manifest exists", MANIFEST_PATH.is_file())
    check("D pdf_removed true", man.get("pdf_removed") is True, str(man.get("pdf_removed")))
    check("D status complete", man.get("status") == "complete", str(man.get("status")))
    check("D range 0-59", man.get("downloaded_start") == 0 and man.get("downloaded_end") == 59)
    check("D sha256 present", bool(man.get("sha256")))
    check("D page_count present", (man.get("page_count") or 0) > 0)
    check("D chapters kept", chapter_count() == chapters_before == 60)
    check("D source meta kept", bool(man.get("source_url")) and man.get("source") == "penana")

    # refuse deleting original
    import importlib.util

    spec = importlib.util.spec_from_file_location("sync_novel_mod", SCRIPTS / "sync_novel.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    check("D refuse original", mod.safe_remove_temp_pdf(LOCAL_ORIGINAL) is False)
    check("D original intact", LOCAL_ORIGINAL.is_file())


def test_safety_paths() -> None:
    print("\n--- Safety: path guards ---")
    import importlib.util

    spec = importlib.util.spec_from_file_location("sync_novel_mod2", SCRIPTS / "sync_novel.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    backup_docx = ROOT / "novel" / "source" / "backup" / "小說備份-第一、二季.docx"
    check("refuse backup docx", mod.safe_remove_temp_pdf(backup_docx) is False)
    check("backup docx intact", backup_docx.is_file())
    # non-pdf under downloads
    txt = DOWNLOADS_DIR / "penana-latest.txt"
    check("refuse txt in downloads", mod.safe_remove_temp_pdf(txt) is False)
    check("txt intact", txt.is_file())


def main() -> int:
    print("=== star_novel sync pipeline tests ===")
    test_a_already_up_to_date()
    test_b_update_required_dry_run()
    test_c_parse_failure_keeps_pdf()
    test_d_success_cleans_pdf()
    test_safety_paths()

    # leave repo in clean complete state (no temp PDF)
    ensure_baseline_manifest()
    if TEMP_PDF.is_file():
        TEMP_PDF.unlink()
        man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        man["pdf_removed"] = True
        man["status"] = "complete"
        man["parser_result"] = "ok"
        MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
