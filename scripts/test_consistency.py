#!/usr/bin/env python3
"""Tests for the Consistency / Quality Gate (phase 3D).

Run: python scripts/test_consistency.py
Also collected by: python -m pytest -q

18 tests with temporary fixtures under novel/drafts/ (auto-cleaned).
Checker is check-only; fixtures never touch canon/plot/review/chapters.
"""
from __future__ import annotations

import atexit
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "novel" / "editor"
DRAFTS = ROOT / "novel" / "drafts"

sys.path.insert(0, str(EDITOR))
import consistency_checker as cc

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


def cleanup_tmp() -> None:
    for p in _TMP:
        try:
            if p.is_file():
                p.unlink()
        except Exception:
            pass
    _TMP.clear()


atexit.register(cleanup_tmp)


def craft(name: str, body: str, target: str = "chapter-060") -> Path:
    fm = [
        "---",
        'draft_id: "draft-tc-001"',
        f'target: "{target}"',
        'request: "test"',
        'request_type: "CONTINUE"',
        'status: "DRAFT"',
        'canon_version: "test"',
        'generated_at: "2026-01-01T00:00:00+00:00"',
        "needs_author_decision: false",
        "conflicts_used: []",
        "proposed_used: []",
        "inferred_used: []",
        'source_chapters: ["059"]',
        "warnings: []",
        "source_trace: []",
        "---",
    ]
    p = DRAFTS / name
    p.write_text("\n".join(fm) + "\n\n" + body, encoding="utf-8")
    _TMP.append(p)
    return p


def run_report(path: Path) -> dict:
    return cc.Checker(path, None).run(cc.snapshot())


def has_issue(rep: dict, category: str, severity: str = "") -> bool:
    return any(i["category"] == category and (not severity or i["severity"] == severity)
               for i in rep["issues"])


def test_1_normal_pass() -> None:
    p = craft("tc-01.md", "星星在邊境防線醒來。蛛皇已死，戰場正在打掃。百里清點人數。\n")
    rep = run_report(p)
    check("T1 status PASS", rep["status"] == "PASS", rep["status"])
    check("T1 zero issues", not rep["issues"], str(len(rep["issues"])))


def test_2_unknown_character() -> None:
    p = craft("tc-02.md", "星星在邊境防線醒來。蛛皇已死。新角色「TestHero」現身營地。\n")
    rep = run_report(p)
    check("T2 WARNING/yr", rep["status"] == "WARNING", rep["status"])
    check("T2 unknown entity", has_issue(rep, "UNKNOWN_ENTITY", "WARNING"))


def test_3_unknown_ability() -> None:
    p = craft("tc-03.md", "星星在邊境防線醒來。新能力「TestPower」在她手中成形。\n")
    rep = run_report(p)
    check("T3 unknown ability", has_issue(rep, "UNKNOWN_ENTITY", "WARNING"))


def test_4_unknown_weapon() -> None:
    p = craft("tc-04.md", "星星在邊境防線醒來。新武器「TestBlade」插在地上。\n")
    rep = run_report(p)
    check("T4 unknown weapon", has_issue(rep, "UNKNOWN_ENTITY", "WARNING"))


def test_5_dead_reappears() -> None:
    p = craft("tc-05.md", "深淵蛛皇站在眾人面前，毫髮無傷，氣息完整。\n")
    rep = run_report(p)
    check("T5 ERROR status", rep["status"] == "ERROR", rep["status"])
    check("T5 character status", has_issue(rep, "CHARACTER_STATUS", "ERROR"))


def test_6_ability_violation() -> None:
    p = craft("tc-06.md", "百里開啟發散，神力暴漲，親自迎戰魔物。\n")
    rep = run_report(p)
    check("T6 ability owner ERROR", has_issue(rep, "ABILITY", "ERROR"))


def test_7_proposed_usage() -> None:
    p = craft("tc-07.md", "星星拿出Stellar星斧，直指前方的敵人。\n")
    rep = run_report(p)
    check("T7 proposed WARNING", has_issue(rep, "PROPOSED_USAGE", "WARNING"))


def test_8_inferred_as_fact() -> None:
    p = craft("tc-08.md", "星星身世空白，但她早就知道自己的父母是誰。\n")
    rep = run_report(p)
    check("T8 inferred WARNING", has_issue(rep, "INFERRED_USAGE", "WARNING"))


def test_9_unresolved_conflict() -> None:
    p = craft("tc-09.md", "神裔家族的長老正在密謀新的計劃，目標直指學院。\n")
    rep = run_report(p)
    check("T9 conflict WARNING", has_issue(rep, "CONFLICT", "WARNING"))


def test_10_c004() -> None:
    p = craft("tc-10.md", "無生血界籠罩了整個戰場，眾人動彈不得。\n")
    rep = run_report(p)
    issues = [i for i in rep["issues"] if i["category"] == "CONFLICT"]
    check("T10 C-004 WARNING", any(i["severity"] == "WARNING" for i in issues))
    check("T10 needs decision",
          any("NEEDS_AUTHOR_DECISION" in i["recommendation"] for i in issues))


def test_11_ai_idea() -> None:
    p = craft("tc-11.md", "星星後續可因某事件短暫接觸到雨之國而展開跨國支線。\n")
    rep = run_report(p)
    check("T11 AI IDEA WARNING", has_issue(rep, "AI_IDEA_USAGE", "WARNING"))


def test_12_timeline() -> None:
    p = craft("tc-12.md", "眾人回憶起第99章發生了大戰，至今心有餘悸。\n")
    rep = run_report(p)
    check("T12 timeline ERROR", has_issue(rep, "TIMELINE", "ERROR"))


def test_13_continuity_059() -> None:
    p = craft("tc-13.md", "星星在教室裡睡午覺，陽光很好，什麼事也沒發生。\n")
    rep = run_report(p)
    check("T13 continuity WARNING", has_issue(rep, "CONTINUITY_059", "WARNING"))


def test_14_foreshadowing() -> None:
    p = craft("tc-14.md", "胡同口的黑色信物閃著微光，無人理會。\n")
    rep = run_report(p)
    check("T14 foreshadowing WARNING", has_issue(rep, "FORESHADOWING", "WARNING"))


def _snapshot() -> dict[str, tuple[int, float]]:
    snap: dict[str, tuple[int, float]] = {}
    for rel in cc.PROTECTED_DIRS:
        for f in (ROOT / rel).rglob("*"):
            if f.is_file():
                st = f.stat()
                snap[f.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def test_15_protected_unchanged() -> None:
    before = _snapshot()
    p = craft("tc-15.md", "星星在邊境防線醒來。蛛皇已死。\n")
    run_report(p)
    after = _snapshot()
    check("T15 protected unchanged", before == after, f"{len(before)} files")


def test_16_json_schema() -> None:
    schema = json.loads((EDITOR / "consistency-schema.json").read_text(encoding="utf-8"))
    p = craft("tc-16.md", "星星在邊境防線醒來。蛛皇已死。\n")
    rep = run_report(p)
    missing = [k for k in schema["required"] if k not in rep]
    check("T16 top keys", not missing, ",".join(missing))
    check("T16 status enum", rep["status"] in ("PASS", "WARNING", "ERROR"))
    issue_req = schema["properties"]["issues"]["items"]["required"]
    bad = [i for i in rep["issues"] if any(k not in i for k in issue_req)]
    check("T16 issue keys", not bad)
    check("T16 severity enum",
          all(i["severity"] in ("ERROR", "WARNING", "INFO") for i in rep["issues"]))


def test_17_markdown() -> None:
    p = craft("tc-17.md", "星星在邊境防線醒來。蛛皇已死。新角色「TestHero」現身。\n")
    rep = run_report(p)
    md = cc.to_markdown(rep)
    check("T17 title", "# Consistency Report" in md)
    check("T17 summary", "## Summary" in md)
    check("T17 protected section", "## Protected Files" in md)
    check("T17 warnings listed", "TestHero" in md)


def test_18_strict() -> None:
    p = craft("tc-18.md", "星星在邊境防線醒來。新角色「TestHero」現身。\n")
    rc_normal = cc.main([str(p)])
    rc_strict = cc.main([str(p), "--strict"])
    check("T18 normal exit 0 on WARNING", rc_normal == 0, f"rc={rc_normal}")
    check("T18 strict exit 1 on WARNING", rc_strict == 1, f"rc={rc_strict}")


def main() -> int:
    print("=== consistency gate tests ===")
    try:
        test_1_normal_pass()
        test_2_unknown_character()
        test_3_unknown_ability()
        test_4_unknown_weapon()
        test_5_dead_reappears()
        test_6_ability_violation()
        test_7_proposed_usage()
        test_8_inferred_as_fact()
        test_9_unresolved_conflict()
        test_10_c004()
        test_11_ai_idea()
        test_12_timeline()
        test_13_continuity_059()
        test_14_foreshadowing()
        test_15_protected_unchanged()
        test_16_json_schema()
        test_17_markdown()
        test_18_strict()
    finally:
        cleanup_tmp()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
