#!/usr/bin/env python3
"""Tests for the Novel Writer draft pipeline (phase 3C).

Run: python scripts/test_writer.py
Also collected by: python -m pytest -q

15 tests: mock generation, Context Builder mediation, chapters/canon
immutability, conflict/proposed/inferred safety, [NEW_SETTING],
unconfigured-LLM exit, API key hygiene, metadata, schema, bad chapter
refs, unknown entities, protected dirs. Mock only; never writes fiction.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "novel" / "editor"
DRAFTS = ROOT / "novel" / "drafts"

sys.path.insert(0, str(EDITOR))
import context_builder as cb


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


writer = _load("writer_mod", EDITOR / "writer.py")
dv = _load("dv_mod", EDITOR / "draft-validator.py")

PASS: list[str] = []
FAIL: list[str] = []
_TMP: list[Path] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"PASS: {name}" + (f" - {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"FAIL: {name}" + (f" - {detail}" if detail else ""))


def make_draft_file(request: str, name: str) -> Path:
    draft, _ = writer.build_draft(request, "mock", max_items=20)
    p = DRAFTS / name
    p.write_text(writer.render_draft_file(draft), encoding="utf-8")
    _TMP.append(p)
    return p


def cleanup_tmp() -> None:
    for p in _TMP:
        try:
            if p.is_file():
                p.unlink()
        except Exception:
            pass
    _TMP.clear()


def snapshot(*rel_dirs: str) -> dict[str, tuple[int, float]]:
    snap: dict[str, tuple[int, float]] = {}
    for rel in rel_dirs:
        for p in (ROOT / rel).rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


PROTECTED = ("novel/source/original", "novel/source/backup", "novel/chapters",
             "novel/canon", "novel/plot", "novel/review")


def test_1_mock_generates() -> None:
    draft, body = writer.build_draft("續寫第60章", "mock", max_items=20)
    check("T1 mock body", "[MOCK DRAFT]" in body)
    check("T1 status DRAFT", draft["status"] == "DRAFT")
    check("T1 no real fiction", "第六十章" not in body or "[MOCK DRAFT]" in body)


def test_2_via_context_builder() -> None:
    draft, _ = writer.build_draft("寫星星與沐寒戰鬥", "mock", max_items=20)
    check("T2 type matches builder",
          draft["request_type"] == cb.classify("寫星星與沐寒戰鬥"))
    check("T2 has source_trace", len(draft["source_trace"]) > 0)
    src = (EDITOR / "writer.py").read_text(encoding="utf-8")
    check("T2 imports builder", "import context_builder" in src)


def test_3_no_chapter_writes() -> None:
    before = snapshot("novel/chapters")
    try:
        make_draft_file("續寫第60章", "w-t3-001.md")
    finally:
        pass
    after = snapshot("novel/chapters")
    check("T3 chapters untouched", before == after, f"{len(before)} files")


def test_4_no_canon_modification() -> None:
    before = snapshot("novel/canon", "novel/plot", "novel/review")
    try:
        make_draft_file("寫星星與沐寒戰鬥", "w-t4-001.md")
        make_draft_file("這次採用 Stellar 星斧", "w-t4-002.md")
    finally:
        pass
    after = snapshot("novel/canon", "novel/plot", "novel/review")
    check("T4 canon/plot/review untouched", before == after)


def test_5_conflict_warning() -> None:
    draft, body = writer.build_draft("無生血界是什麼", "mock", max_items=20)
    check("T5 C-004 used", "C-004" in draft["conflicts_used"])
    check("T5 needs decision", draft["needs_author_decision"] is True)
    check("T5 marker block", "[NEEDS_AUTHOR_DECISION]" in body)
    check("T5 warning text",
          any("Do not resolve automatically" in w for w in draft["warnings"]))


def test_6_proposed_not_upgraded() -> None:
    draft, body = writer.build_draft("寫星星與沐寒戰鬥", "mock", max_items=20)
    check("T6 proposed_used empty by default", draft["proposed_used"] == [])
    check("T6 no fact wording", "是星星正式武器" not in body)
    d2, _ = writer.build_draft("這次採用 Stellar 星斧", "mock", max_items=20)
    adopted = d2["proposed_used"]
    check("T6 explicit adopt recorded", len(adopted) > 0, ",".join(adopted))


def test_7_inferred_marked() -> None:
    draft, _ = writer.build_draft("寫星星與沐寒戰鬥", "mock", max_items=20)
    check("T7 inferred listed", len(draft["inferred_used"]) > 0)
    ctx = cb.build_context("寫星星與沐寒戰鬥", max_items=20)
    ok = all(i["status"] == "INFERRED" and i["confidence"] and i["source"]
             for i in ctx["review"]["inferred"])
    check("T7 confidence kept", ok)


def _craft(name: str, fm_lines: list[str], body: str) -> Path:
    p = DRAFTS / name
    p.write_text("---\n" + "\n".join(fm_lines) + "\n---\n\n" + body,
                 encoding="utf-8")
    _TMP.append(p)
    return p


def _base_fm(**over) -> list[str]:
    base = {
        "draft_id": '"draft-w-001"',
        "target": '"chapter-060"',
        "request": '"test"',
        "request_type": '"CONTINUE"',
        "status": '"DRAFT"',
        "canon_version": '"test"',
        "generated_at": '"2026-01-01T00:00:00+00:00"',
        "needs_author_decision": "false",
        "conflicts_used": "[]",
        "proposed_used": "[]",
        "inferred_used": "[]",
        "source_chapters": '["059"]',
        "warnings": "[]",
        "source_trace": "[]",
    }
    base.update(over)
    return [f"{k}: {v}" for k, v in base.items()]


def test_8_new_setting() -> None:
    p = _craft("w-t8-001.md",
               _base_fm(**{"conflicts_used": '["C-001"]'}),
               "[MOCK DRAFT]\n新角色「 tested_nonexistent_hero 」登場。\n")
    fails, warns, new, _ = dv.validate(p)
    check("T8 new setting flagged", len(new) > 0, ";".join(new)[:60])
    check("T8 not a failure", not fails, ",".join(fails))


def test_9_llm_unconfigured() -> None:
    env = {k: v for k, v in os.environ.items()
           if k not in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")}
    proc = subprocess.run(
        [sys.executable, str(EDITOR / "writer.py"), "--request", "續寫第60章",
         "--provider", "openai-compatible"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    check("T9 safe exit", proc.returncode == 2, f"rc={proc.returncode}")
    check("T9 message", "LLM provider is not configured." in out)


def test_10_no_key_leak() -> None:
    env = dict(os.environ)
    env["LLM_API_KEY"] = "sk-test-DO-NOT-LEAK-12345"
    proc = subprocess.run(
        [sys.executable, str(EDITOR / "writer.py"), "--request", "續寫第60章",
         "--provider", "mock"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    check("T10 key absent", "sk-test-DO-NOT-LEAK-12345" not in out)


def test_11_metadata_correct() -> None:
    p = make_draft_file("續寫第60章", "w-t11-001.md")
    fails, _, _, _ = dv.validate(p)
    check("T11 validator clean", not fails, ",".join(fails))


def test_12_schema_legal() -> None:
    schema = json.loads((EDITOR / "writer-schema.json").read_text(encoding="utf-8"))
    draft, _ = writer.build_draft("續寫第60章", "mock", max_items=20)
    full = dict(draft)
    full["content"] = draft["content"]
    missing = [k for k in schema["required"] if k not in full]
    check("T12 schema keys", not missing, ",".join(missing))
    check("T12 status enum", draft["status"] in schema["properties"]["status"]["enum"])


def test_13_bad_chapter_detected() -> None:
    p = _craft("w-t13-001.md", _base_fm(), "測試正文提到第99章的事件。\n")
    fails, _, _, _ = dv.validate(p)
    check("T13 bad chapter fails",
          any("nonexistent" in f for f in fails), ",".join(fails))


def test_14_unknown_entities_marked() -> None:
    p = _craft("w-t14-001.md", _base_fm(),
               "新能力「 tested_nonexistent_power 」爆發，新武器「 tested_nonexistent_blade 」出鞘。\n")
    _fails, _warns, new, _ = dv.validate(p)
    check("T14 unknowns flagged", len(new) >= 2, ";".join(new)[:80])


def test_15_protected_zero_change() -> None:
    before = snapshot(*PROTECTED)
    try:
        for r in ["續寫第60章", "寫星星與沐寒戰鬥"]:
            d, _ = writer.build_draft(r, "mock", max_items=20)
            p = DRAFTS / "w-t15-tmp.md"
            p.write_text(writer.render_draft_file(d), encoding="utf-8")
            dv.validate(p)
            p.unlink()
    finally:
        pass
    after = snapshot(*PROTECTED)
    check("T15 protected unchanged", before == after, f"{len(before)} files")


def main() -> int:
    print("=== writer pipeline tests (mock only) ===")
    try:
        test_1_mock_generates()
        test_2_via_context_builder()
        test_3_no_chapter_writes()
        test_4_no_canon_modification()
        test_5_conflict_warning()
        test_6_proposed_not_upgraded()
        test_7_inferred_marked()
        test_8_new_setting()
        test_9_llm_unconfigured()
        test_10_no_key_leak()
        test_11_metadata_correct()
        test_12_schema_legal()
        test_13_bad_chapter_detected()
        test_14_unknown_entities_marked()
        test_15_protected_zero_change()
    finally:
        cleanup_tmp()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
