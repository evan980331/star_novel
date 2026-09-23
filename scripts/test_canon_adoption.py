#!/usr/bin/env python3
"""Tests for Canon Adoption / Author Approval (phase 3E).

Run: python scripts/test_canon_adoption.py
Also collected by: python -m pytest -q

20 tests against an isolated fixture repo under the system temp dir.
The real novel/canon, plot, review, chapters and source trees are NEVER
written by these tests (T15 asserts zero change). No destructive testing
on the real canon.
"""
from __future__ import annotations

import atexit
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "novel" / "editor"

sys.path.insert(0, str(EDITOR))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adopter = _load("adopter_mod", EDITOR / "canon_adopter.py")

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
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                p.unlink()
        except Exception:
            pass
    _TMP.clear()


atexit.register(cleanup_tmp)

DRAFT_BODY = """---
draft_id: "draft-chapter-060-001"
target: "chapter-060"
request: "test adoption"
request_type: "CONTINUE"
status: "DRAFT"
canon_version: "test"
generated_at: "2026-01-01T00:00:00+00:00"
needs_author_decision: false
conflicts_used: []
proposed_used: []
inferred_used: []
source_chapters: ["059"]
warnings: []
source_trace: []
---

星星在邊境防線醒來。新角色「TestHero」現身營地。
新能力「TestPower」在她手中成形。已知設定：星星是主角。
"""


def make_repo(extra_body: str = "") -> Path:
    """Minimal isolated fixture repo (never the real canon)."""
    root = Path(tempfile.mkdtemp(prefix="adopt3e_"))
    _TMP.append(root)
    (root / "novel" / "canon").mkdir(parents=True)
    (root / "novel" / "review").mkdir(parents=True)
    (root / "novel" / "drafts").mkdir(parents=True)
    (root / "novel" / "adoptions").mkdir(parents=True)
    (root / "novel" / "chapters").mkdir(parents=True)
    (root / "novel" / "plot").mkdir(parents=True)
    (root / "novel" / "canon" / "characters.md").write_text(
        "# Canon\n\n## 星星\n\n- 主角。Source: Chapter #001\n", encoding="utf-8")
    for name in ["abilities.md", "weapons.md", "factions.md", "locations.md",
                 "terminology.md", "relationships.md", "timeline.md"]:
        (root / "novel" / "canon" / name).write_text(
            "# Canon\n\n## 佔位\n\n- 佔位條目。\n", encoding="utf-8")
    (root / "novel" / "review" / "conflicts.md").write_text(
        "# Conflicts\n\n## C-004\n\n### 類型\n設定衝突\n\n"
        "### 衝突內容\n無生血界標記矛盾\n\n### 目前狀態\n[UNRESOLVED]\n",
        encoding="utf-8")
    (root / "novel" / "review" / "proposed.md").write_text(
        "# Proposed\n\n### P-900 TestProp\n- 原始內容：測試提案。\n", encoding="utf-8")
    (root / "novel" / "review" / "inferred.md").write_text(
        "# Inferred\n\n### I-A99 測試推論\n- 內容：測試。\n", encoding="utf-8")
    (root / "novel" / "review" / "author-decisions.md").write_text(
        "# 作者決策表\n\n## 待確認\n\n| C-004 | 衝突 | 無生血界 | 術語 | 待確認 |\n\n"
        "## 已確認\n\n尚無\n", encoding="utf-8")
    for d in ["source/original", "source/backup"]:
        (root / "novel" / d).mkdir(parents=True)
    (root / "novel" / "chapters" / "059.md").write_text("#059\n正文。\n", encoding="utf-8")
    (root / "novel" / "drafts" / "chapter-060-v1.md").write_text(
        DRAFT_BODY + extra_body, encoding="utf-8")
    return root


def gen(root: Path, extra: str = "") -> tuple[Path, dict]:
    if extra:
        p = root / "novel" / "drafts" / "chapter-060-v1.md"
        p.write_text(DRAFT_BODY + extra, encoding="utf-8")
    jpath, _mpath = adopter.generate(root / "novel" / "drafts" / "chapter-060-v1.md", root)
    return jpath, json.loads(jpath.read_text(encoding="utf-8"))


def canon_snapshot(root: Path) -> dict:
    snap = {}
    for p in (root / "novel" / "canon").rglob("*"):
        if p.is_file():
            snap[p.name] = p.read_text(encoding="utf-8")
    return snap


def real_snapshot() -> dict:
    snap = {}
    for rel in ["novel/canon", "novel/plot", "novel/review",
                "novel/chapters", "novel/source/original", "novel/source/backup"]:
        for p in (ROOT / rel).rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def test_1_generate_no_canon_change() -> None:
    root = make_repo()
    before = canon_snapshot(root)
    jpath, adoption = gen(root)
    check("T1 adoption files", jpath.is_file() and jpath.with_suffix(".md").is_file())
    check("T1 canon untouched", canon_snapshot(root) == before)


def test_2_default_pending() -> None:
    root = make_repo()
    _j, adoption = gen(root)
    check("T2 has changes", len(adoption["changes"]) >= 2, str(len(adoption["changes"])))
    check("T2 all PENDING",
          all(c["approval"] == "PENDING" for c in adoption["changes"]))
    check("T2 confidence candidate",
          all(c["confidence"] == "candidate" for c in adoption["changes"]))


def test_3_approve_one() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    ok, _ = adopter.approve(jpath, [first], root)
    after = json.loads(jpath.read_text(encoding="utf-8"))
    got = [c for c in after["changes"] if c["id"] == first][0]
    check("T3 approve ok", ok and got["approval"] == "APPROVED")


def test_4_reject_one() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    ok, _ = adopter.reject(jpath, [first], root)
    after = json.loads(jpath.read_text(encoding="utf-8"))
    got = [c for c in after["changes"] if c["id"] == first][0]
    check("T4 reject ok", ok and got["approval"] == "REJECTED")


def test_5_approve_multi() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    ids = [c["id"] for c in adoption["changes"][:2]]
    ok, _ = adopter.approve(jpath, ids, root)
    after = json.loads(jpath.read_text(encoding="utf-8"))
    check("T5 approve multi",
          ok and all(c["approval"] == "APPROVED"
                     for c in after["changes"] if c["id"] in ids))


def test_6_approve_all_clean() -> None:
    root = make_repo()
    jpath, _adoption = gen(root)
    ok, msg = adopter.approve_all(jpath, root)
    after = json.loads(jpath.read_text(encoding="utf-8"))
    check("T6 approve-all ok", ok, msg)
    check("T6 all approved",
          all(c["approval"] == "APPROVED" for c in after["changes"]))


def test_7_approve_all_conflict_refused() -> None:
    root = make_repo("新術語「無生血界」籠罩了整個戰場。\n")
    jpath, adoption = gen(root)
    blocked = [c["id"] for c in adoption["changes"] if c["approval"] == "BLOCKED"]
    check("T7 C-004 blocked at generate", len(blocked) > 0, ",".join(blocked))
    ok, msg = adopter.approve_all(jpath, root)
    check("T7 approve-all refused", not ok, msg[:80])


def test_8_c004_blocked() -> None:
    root = make_repo("新術語「無生血界」籠罩了整個戰場。\n")
    jpath, adoption = gen(root)
    blocked = [c for c in adoption["changes"] if c["approval"] == "BLOCKED"]
    check("T8 blocked exists", len(blocked) > 0)
    ok, msg = adopter.approve(jpath, [blocked[0]["id"]], root)
    check("T8 approve refused", not ok, msg[:80])
    after = json.loads(jpath.read_text(encoding="utf-8"))
    got = [c for c in after["changes"] if c["id"] == blocked[0]["id"]][0]
    check("T8 stays BLOCKED", got["approval"] == "BLOCKED")


def _prop_repo() -> Path:
    root = make_repo("星星拿出測試提案中的東西。P-900 正式啟用。\n")
    p = root / "novel" / "drafts" / "chapter-060-v1.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("proposed_used: []", 'proposed_used: ["P-900"]')
    p.write_text(text, encoding="utf-8")
    return root


def test_9_proposed_needs_approval() -> None:
    root = _prop_repo()
    jpath, adoption = gen(root)
    props = [c for c in adoption["changes"] if c["source_status"] == "PROPOSED"]
    check("T9 proposed candidate", len(props) > 0)
    check("T9 pending not canon",
          all(c["approval"] == "PENDING" for c in props))
    before = canon_snapshot(root)
    check("T9 canon untouched by generate", canon_snapshot(root) == before)


def test_10_inferred_no_auto_upgrade() -> None:
    root = make_repo()
    p = root / "novel" / "drafts" / "chapter-060-v1.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("inferred_used: []", 'inferred_used: ["I-A99"]')
    p.write_text(text, encoding="utf-8")
    jpath, adoption = gen(root)
    infs = [c for c in adoption["changes"] if c["source_status"] == "INFERRED"]
    check("T10 inferred candidate", len(infs) > 0)
    check("T10 pending only", all(c["approval"] == "PENDING" for c in infs))


def test_11_ai_idea_blocked() -> None:
    root = make_repo()
    (root / "novel" / "ideas").mkdir(parents=True)
    (root / "novel" / "ideas" / "ideas.md").write_text(
        "# Ideas\n\n- [AI IDEA] 測試用AI構想XYZABC，僅供測試。\n", encoding="utf-8")
    p = root / "novel" / "drafts" / "chapter-060-v1.md"
    p.write_text(p.read_text(encoding="utf-8")
                 + "測試用AI構想XYZABC 出現在此。\n", encoding="utf-8")
    jpath, adoption = gen(root)
    ais = [c for c in adoption["changes"] if c["source_status"] == "AI_IDEA"]
    check("T11 ai_idea candidate", len(ais) > 0)
    check("T11 default BLOCKED", all(c["approval"] == "BLOCKED" for c in ais))


def test_12_version_changed_refused() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    adopter.approve(jpath, [first], root)
    adoption = json.loads(jpath.read_text(encoding="utf-8"))
    assert [c for c in adoption["changes"] if c["id"] == first][0]["approval"] == "APPROVED"
    adoption["canon_version"] = "deadbeef"
    jpath.write_text(json.dumps(adoption, ensure_ascii=False, indent=2), encoding="utf-8")
    before = canon_snapshot(root)
    ok, msg = adopter.apply_adoption(jpath, root)
    check("T12 version refused", not ok and "CANON_VERSION_CHANGED" in msg, msg[:70])
    check("T12 canon intact", canon_snapshot(root) == before)


def test_13_atomic_apply() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    adopter.approve(jpath, [first], root)
    # inject an impossible UPDATE to force mid-apply failure
    adoption["changes"].append({
        "id": "A-999", "type": "CHARACTER", "action": "UPDATE",
        "target": "不存在的章節標題XYZ", "field": "content",
        "old_value": None, "new_value": "x", "source": "test",
        "evidence": "x", "confidence": "candidate",
        "approval": "APPROVED", "source_status": "NEW_SETTING",
        "blocked_reason": None})
    jpath.write_text(json.dumps(adoption, ensure_ascii=False, indent=2), encoding="utf-8")
    before = canon_snapshot(root)
    ok, _msg = adopter.apply_adoption(jpath, root)
    check("T13 apply fails", not ok)
    check("T13 canon all-or-nothing", canon_snapshot(root) == before)


def test_14_adoption_log() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    adopter.approve(jpath, [first], root)
    ok, msg = adopter.apply_adoption(jpath, root)
    logs = sorted((root / "novel" / "adoptions").glob("*-adoption-log.json"))
    check("T14 applied", ok, msg[:80])
    check("T14 log exists", len(logs) > 0)
    if logs:
        log = json.loads(logs[-1].read_text(encoding="utf-8"))
        check("T14 log keys",
              all(k in log for k in ["adoption_id", "draft", "canon_before",
                                     "canon_after", "approved_changes",
                                     "rejected_changes", "timestamp", "status"]))
        check("T14 log status", log["status"] == "APPLIED")


def test_15_protected_real_repo() -> None:
    before = real_snapshot()
    root = make_repo()
    gen(root)
    check("T15 real repo untouched", real_snapshot() == before)


def test_16_no_delete_canon() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    adoption["changes"].append({
        "id": "A-998", "type": "CHARACTER", "action": "DELETE",
        "target": "星星", "field": "content", "old_value": "x",
        "new_value": "", "source": "test", "evidence": "x",
        "confidence": "candidate", "approval": "APPROVED",
        "source_status": "NEW_SETTING", "blocked_reason": None})
    jpath.write_text(json.dumps(adoption, ensure_ascii=False, indent=2), encoding="utf-8")
    before = canon_snapshot(root)
    ok, _msg = adopter.apply_adoption(jpath, root)
    check("T16 DELETE refused", not ok)
    check("T16 canon intact", canon_snapshot(root) == before)


def test_17_no_chapter_write() -> None:
    root = make_repo()
    jpath, _adoption = gen(root)
    targets = [c for c in json.loads(jpath.read_text(encoding="utf-8"))["changes"]]
    paths = {adopter.TARGET_FILE[c["type"]] for c in targets}
    check("T17 no chapters target",
          not any(p.startswith("novel/chapters") or p.startswith("novel/source")
                  for p in paths))
    before = (root / "novel" / "chapters" / "059.md").read_text(encoding="utf-8")
    adopter.approve(jpath, [targets[0]["id"]], root)
    adopter.apply_adoption(jpath, root)
    check("T17 chapters intact",
          (root / "novel" / "chapters" / "059.md").read_text(encoding="utf-8") == before)


def test_18_schema_valid() -> None:
    schema = json.loads((EDITOR / "adoption-schema.json").read_text(encoding="utf-8"))
    root = make_repo()
    jpath, adoption = gen(root)
    missing = [k for k in schema["required"] if k not in adoption]
    check("T18 top keys", not missing, ",".join(missing))
    creq = schema["properties"]["changes"]["items"]["required"]
    bad = [c["id"] for c in adoption["changes"] if any(k not in c for k in creq)]
    check("T18 change keys", not bad, ",".join(bad))
    check("T18 approval enum",
          all(c["approval"] in ("PENDING", "APPROVED", "REJECTED", "BLOCKED")
              for c in adoption["changes"]))


def test_19_repeat_apply_safe() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    first = adoption["changes"][0]["id"]
    adopter.approve(jpath, [first], root)
    ok1, _ = adopter.apply_adoption(jpath, root)
    snap = canon_snapshot(root)
    ok2, msg2 = adopter.apply_adoption(jpath, root)
    check("T19 first apply ok", ok1)
    check("T19 repeat refused", not ok2, msg2[:60])
    check("T19 canon stable", canon_snapshot(root) == snap)


def test_20_rejected_excluded() -> None:
    root = make_repo()
    jpath, adoption = gen(root)
    ids = [c["id"] for c in adoption["changes"][:2]]
    adopter.approve(jpath, [ids[0]], root)
    adopter.reject(jpath, [ids[1]], root)
    rej = [c for c in json.loads(jpath.read_text(encoding="utf-8"))["changes"]
           if c["id"] == ids[1]][0]
    ok, _ = adopter.apply_adoption(jpath, root)
    chars = (root / "novel" / "canon" / "characters.md").read_text(encoding="utf-8")
    abils = (root / "novel" / "canon" / "abilities.md").read_text(encoding="utf-8")
    check("T20 applied", ok)
    check("T20 rejected target absent",
          rej["target"] not in chars and rej["target"] not in abils,
          rej["target"])


def main() -> int:
    print("=== canon adoption tests (fixture repos only) ===")
    try:
        test_1_generate_no_canon_change()
        test_2_default_pending()
        test_3_approve_one()
        test_4_reject_one()
        test_5_approve_multi()
        test_6_approve_all_clean()
        test_7_approve_all_conflict_refused()
        test_8_c004_blocked()
        test_9_proposed_needs_approval()
        test_10_inferred_no_auto_upgrade()
        test_11_ai_idea_blocked()
        test_12_version_changed_refused()
        test_13_atomic_apply()
        test_14_adoption_log()
        test_15_protected_real_repo()
        test_16_no_delete_canon()
        test_17_no_chapter_write()
        test_18_schema_valid()
        test_19_repeat_apply_safe()
        test_20_rejected_excluded()
    finally:
        cleanup_tmp()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
