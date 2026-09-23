#!/usr/bin/env python3
"""Tests for the canon review system (phase 3A).

Run: python scripts/test_canon_review.py
Also collected by: python -m pytest -q
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = ROOT / "novel" / "review"
CANON_DIR = ROOT / "novel" / "canon"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"PASS: {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"FAIL: {name}" + (f" — {detail}" if detail else ""))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_review_dir_complete() -> None:
    for name in ["README.md", "conflicts.md", "proposed.md",
                 "inferred.md", "author-decisions.md", "review-status.json"]:
        check(f"review/{name} exists", (REVIEW_DIR / name).is_file())


def test_conflicts_tracked() -> None:
    text = read("novel/review/conflicts.md")
    ids = re.findall(r"^## (C-\d+)", text, re.M)
    check("conflicts >= 1", len(ids) >= 1, f"{len(ids)} entries")
    check("conflicts all UNRESOLVED or tracked",
          "[UNRESOLVED]" in text or "[RESOLVED]" in text)
    check("no self-decided canon", "自行決定" not in text.replace("不得自行決定", ""))


def test_proposed_tracked() -> None:
    text = read("novel/review/proposed.md")
    ids = re.findall(r"^### (P-\d+)", text, re.M)
    check("proposed >= 1", len(ids) >= 1, f"{len(ids)} entries")
    for bad in ["[ACCEPTED]", "[REJECTED]", "[SUPERSEDED]"]:
        check(f"no premature {bad}", bad not in text)


def test_inferred_sourced() -> None:
    text = read("novel/review/inferred.md")
    for sec in ["I-A", "I-B", "I-C"]:
        check(f"inferred section {sec}", sec in text)
    check("no auto-upgrade claim", "自動升級" in text and "不得" in text)


def test_ai_idea_out_of_canon() -> None:
    bad = []
    for p in CANON_DIR.glob("*.md"):
        if p.name == "README.md":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "[AI IDEA]" in line:
                bad.append(f"{p.name}:{i}")
    check("no [AI IDEA] in canon (README excepted)", not bad, "; ".join(bad))


def test_review_status_correct() -> None:
    status = json.loads(read("novel/review/review-status.json"))
    c = len(re.findall(r"^## C-\d+", read("novel/review/conflicts.md"), re.M))
    p = len(re.findall(r"^### P-\d+", read("novel/review/proposed.md"), re.M))
    ia = len(re.findall(r"^### I-A\d+", read("novel/review/inferred.md"), re.M))
    ib = len(re.findall(r"^### I-B\d+", read("novel/review/inferred.md"), re.M))
    ic = len(re.findall(r"^### I-C\d+", read("novel/review/inferred.md"), re.M))
    check("status conflicts.total", status["conflicts"]["total"] == c, f"{c}")
    check("status proposed.total", status["proposed"]["total"] == p, f"{p}")
    check("status inferred.total", status["inferred"]["total"] == ia + ib + ic)
    check("status inferred.high", status["inferred"]["high"] == ia)
    check("status inferred.medium", status["inferred"]["medium"] == ib)
    check("status inferred.low", status["inferred"]["low"] == ic)


def test_author_decision_gap_detectable() -> None:
    conflicts = read("novel/review/conflicts.md")
    decisions = read("novel/review/author-decisions.md")
    cids = re.findall(r"^## (C-\d+)", conflicts, re.M)
    missing = [c for c in cids if c not in decisions]
    check("all conflicts in author-decisions", not missing, "; ".join(missing))


def test_audit_review_mode_exit_0() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_canon.py"), "--review"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    check("audit --review exit 0", proc.returncode == 0, f"rc={proc.returncode}")


def main() -> int:
    print("=== canon review tests ===")
    test_review_dir_complete()
    test_conflicts_tracked()
    test_proposed_tracked()
    test_inferred_sourced()
    test_ai_idea_out_of_canon()
    test_review_status_correct()
    test_author_decision_gap_detectable()
    test_audit_review_mode_exit_0()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
