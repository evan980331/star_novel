#!/usr/bin/env python3
"""Tests for the Novel Editor Context Engine (phase 3B).

Run: python scripts/test_editor_context.py
Also collected by: python -m pytest -q

Covers: CONTINUE retrieval, BATTLE retrieval, conflict/proposed/inferred
safety, AI IDEA exclusion, source trace, --max-items, unknown requests,
protected-file immutability. Read-only; never writes fiction.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "novel" / "editor"))

import context_builder as cb

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"PASS: {name}" + (f" - {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"FAIL: {name}" + (f" - {detail}" if detail else ""))


def capped_count(ctx: dict) -> int:
    n = sum(len(v) for v in ctx["canon"].values())
    n += sum(len(v) for v in ctx["plot"].values())
    n += len(ctx["review"]["proposed"]) + len(ctx["review"]["inferred"])
    return n


def test_1_continue_chapter_60() -> None:
    ctx = cb.build_context("續寫第60章", max_items=60)
    check("T1 task CONTINUE", ctx["task_type"] == "CONTINUE", ctx["task_type"])
    check("T1 chapter 59 excerpt",
          any("059" in c["name"] for c in ctx["plot"]["chapters"]))
    check("T1 current-arc", len(ctx["plot"]["current_arc"]) > 0)
    check("T1 future", len(ctx["plot"]["future"]) > 0)
    check("T1 unresolved", len(ctx["plot"]["unresolved"]) > 0)
    check("T1 foreshadowing", len(ctx["plot"]["foreshadowing"]) > 0)
    check("T1 relevant characters", len(ctx["canon"]["characters"]) > 0)
    check("T1 relevant abilities", len(ctx["canon"]["abilities"]) > 0)
    check("T1 relevant weapons", len(ctx["canon"]["weapons"]) > 0)
    check("T1 conflicts included", len(ctx["review"]["conflicts"]) > 0)
    check("T1 pending decisions",
          len(ctx["review"]["author_decisions_pending"]) > 0)


def test_2_battle_retrieval() -> None:
    ctx = cb.build_context("寫星星與沐寒戰鬥", max_items=40)
    check("T2 task BATTLE", ctx["task_type"] == "BATTLE", ctx["task_type"])
    names = " ".join(i["name"] for i in ctx["canon"]["characters"])
    check("T2 star retrieved", "星星" in names)
    check("T2 muhan retrieved", "沐寒" in names)
    check("T2 abilities", len(ctx["canon"]["abilities"]) > 0)
    check("T2 weapons", len(ctx["canon"]["weapons"]) > 0)


def test_3_conflict_not_resolved() -> None:
    ctx = cb.build_context("無生血界", max_items=40)
    ids = [c["id"] for c in ctx["review"]["conflicts"]]
    check("T3 C-004 surfaced", "C-004" in ids, ",".join(ids))
    check("T3 unresolved kept",
          any(c["status"] == "[UNRESOLVED]" for c in ctx["review"]["conflicts"]))
    check("T3 warning present",
          any("Do not resolve automatically" in w for w in ctx["warnings"]))


def test_4_proposed_kept() -> None:
    ctx = cb.build_context("整理雨之國設定", max_items=40)
    check("T4 proposed present", len(ctx["review"]["proposed"]) > 0)
    check("T4 all PROPOSED",
          all(p["status"] == "PROPOSED" for p in ctx["review"]["proposed"]))
    bad = [p["id"] for p in ctx["review"]["proposed"]
           if "正式武器" in p["title"] and "PROPOSED" not in p["title"]]
    check("T4 no established-fact wording", not bad, ",".join(bad))
    for items in ctx["canon"].values():
        for it in items:
            if it["status"] == "PROPOSED":
                check(f"T4 marker kept {it['name'][:10]}",
                      "[PROPOSED]" in it["text"])
                break


def test_5_inferred_kept() -> None:
    ctx = cb.build_context("寫星星與沐寒戰鬥", max_items=40)
    check("T5 inferred present", len(ctx["review"]["inferred"]) > 0)
    ok = all(i["status"] == "INFERRED" and i["confidence"]
             and i["source"] and i["reason"]
             for i in ctx["review"]["inferred"])
    check("T5 confidence/source/reason", ok)


def test_6_no_ai_idea_in_canon() -> None:
    bad: list[str] = []
    for r in ["寫星星與沐寒戰鬥", "續寫第60章", "分析星星目前能力"]:
        ctx = cb.build_context(r, max_items=60)
        for items in list(ctx["canon"].values()) + list(ctx["plot"].values()):
            for it in items:
                if "[AI IDEA]" in it["text"]:
                    bad.append(it["name"])
    check("T6 no AI IDEA in canon/plot context", not bad, ",".join(bad[:3]))


def test_7_source_trace() -> None:
    ctx = cb.build_context("分析星星目前能力", max_items=40)
    check("T7 trace non-empty", len(ctx["source_trace"]) > 0)
    ok = all(set(s) >= {"type", "name", "source"} and s["source"]
             for s in ctx["source_trace"])
    check("T7 trace shape", ok)
    missing = [src for s in ctx["source_trace"] for src in s["source"]
               if src.endswith(".md") and not (ROOT / src).is_file()]
    check("T7 trace files exist", not missing, ",".join(missing[:3]))


def test_8_max_items() -> None:
    full = cb.build_context("續寫第60章", max_items=1000)
    small = cb.build_context("續寫第60章", max_items=10)
    check("T8 capped", capped_count(small) <= 10, str(capped_count(small)))
    check("T8 conflicts always kept", len(small["review"]["conflicts"]) > 0)
    check("T8 pending always kept",
          len(small["review"]["author_decisions_pending"]) > 0)
    check("T8 truncation warned",
          any("max-items" in w for w in small["warnings"]))
    check("T8 larger holds more",
          capped_count(full) >= capped_count(small))


def test_9_unknown_request() -> None:
    try:
        ctx = cb.build_context("blah xyz 123", max_items=40)
        ok = ctx["task_type"] == "UNKNOWN" and isinstance(ctx["warnings"], list)
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  exception: {exc}")
    check("T9 unknown no crash", ok)


def _snapshot() -> dict[str, tuple[int, float]]:
    snap: dict[str, tuple[int, float]] = {}
    for base in ["novel/source/original", "novel/source/backup", "novel/chapters"]:
        for p in (ROOT / base).rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def test_10_protected_untouched() -> None:
    before = _snapshot()
    for r in ["續寫第60章", "寫星星與沐寒戰鬥", "分析星星目前能力"]:
        cb.build_context(r, max_items=40)
        cb.to_markdown(cb.build_context(r, max_items=10))
    after = _snapshot()
    check("T10 protected unchanged", before == after,
          f"{len(before)} files")
    src = (ROOT / "novel" / "editor" / "context_builder.py").read_text(encoding="utf-8")
    writes = [kw for kw in ["write_text", "unlink", "mkdir", "shutil",
                            "os.remove", "os.rename", '"w"', "'w'"]
              if kw in src]
    check("T10 no write APIs", not writes, ",".join(writes))


def main() -> int:
    print("=== editor context tests ===")
    test_1_continue_chapter_60()
    test_2_battle_retrieval()
    test_3_conflict_not_resolved()
    test_4_proposed_kept()
    test_5_inferred_kept()
    test_6_no_ai_idea_in_canon()
    test_7_source_trace()
    test_8_max_items()
    test_9_unknown_request()
    test_10_protected_untouched()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
