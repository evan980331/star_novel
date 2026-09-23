#!/usr/bin/env python3
"""Tests for Step 3F: agent-driven writing procedure + localhost Web UI.

Run: python scripts/test_writing_procedure.py
Also collected by: python -m pytest -q

Spawns `node web/server.js` on a test port and exercises the HTTP API.
Writing tests target chapter-099 fixtures (cleaned up afterwards).
Real canon/plot/review/chapters/source trees are NEVER written
(snapshot-asserted). No browser tooling exists in this repo, so UI checks
are HTTP-level (status codes, JSON shape, key DOM strings).
"""
from __future__ import annotations

import atexit
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "novel" / "drafts"
ADOPTIONS = ROOT / "novel" / "adoptions"
TEST_PORT = 34579
TEST_CHAPTER = "chapter-099"

PASS: list[str] = []
FAIL: list[str] = []
_SERVER = None


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"PASS: {name}" + (f" - {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"FAIL: {name}" + (f" - {detail}" if detail else ""))


def start_server():
    global _SERVER
    if _SERVER is not None:
        return
    env = dict(__import__("os").environ)
    env["PORT"] = str(TEST_PORT)
    _SERVER = subprocess.Popen(
        ["node", "web/server.js"], cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            get("/api/health")
            return
        except Exception:
            if _SERVER.poll() is not None:
                raise RuntimeError("server exited early")
            time.sleep(1)
    raise RuntimeError("server did not start")


def stop_server():
    global _SERVER
    if _SERVER is not None:
        _SERVER.terminate()
        try:
            _SERVER.wait(timeout=15)
        except Exception:
            _SERVER.kill()
        _SERVER = None


def api(method: str, path: str, data=None, timeout=600):
    url = f"http://127.0.0.1:{TEST_PORT}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get(path: str, timeout=60):
    return api("GET", path, None, timeout)


def chat(msg: str, timeout=600):
    return api("POST", "/api/chat", {"message": msg}, timeout)


ADOPT_PRE = set()


def cleanup_fixtures():
    for p in [DRAFTS / TEST_CHAPTER]:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    try:
        for p in ADOPTIONS.iterdir():
            if p.name not in ADOPT_PRE and p.name != ".gitkeep" and p.is_file():
                p.unlink()
    except Exception:
        pass


def snapshot(*rels: str):
    snap = {}
    for rel in rels:
        base = ROOT / rel
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


PROTECTED = ("novel/source/original", "novel/source/backup", "novel/chapters",
             "novel/canon", "novel/plot", "novel/review")

REAL_SNAP = {}


@pytest.fixture(scope="session", autouse=True)
def _session():
    REAL_SNAP.update(snapshot(*PROTECTED))
    try:
        ADOPT_PRE.update(p.name for p in ADOPTIONS.iterdir())
    except Exception:
        pass
    start_server()
    cleanup_fixtures()
    yield
    cleanup_fixtures()
    stop_server()


atexit.register(stop_server)
atexit.register(cleanup_fixtures)


# -- procedure ---------------------------------------------------------------
LAST_WRITE = {}


def test_1_write_trigger():
    code, o = chat("寫作開始，我要寫第99章")
    check("T1 trigger ok", code == 200 and o["status"] == "waiting_author", str(code))
    check("T1 stages", "DRAFT_GENERATION" in o.get("stages", []))
    LAST_WRITE.update(o)


def test_2_discussion_no_trigger():
    before = snapshot("novel/drafts")
    code, o = chat("你覺得星星和希爾達的關係之後會怎麼發展？")
    check("T2 discussion reply", code == 200 and o["status"] == "idle")
    check("T2 no drafts created", snapshot("novel/drafts") == before)


def test_3_context_built():
    stages = LAST_WRITE.get("stages", [])
    check("T3 context stage", "CONTEXT_BUILD" in stages, ",".join(stages))


def _versions():
    code, o = get("/api/drafts/chapter-099")
    return [v["version"] for v in o.get("versions", [])] if code == 200 else []


def test_4_three_drafts():
    vers = _versions()
    check("T4 v1..v3 exist", all(v in vers for v in ("v1", "v2", "v3")), ",".join(vers))
    if len(vers) >= 3:
        bodies = set()
        for v in ("v1", "v2", "v3"):
            _c, d = get(f"/api/drafts/chapter-099/{v}")
            bodies.add(d.get("content", ""))
        check("T4 versions differ", len(bodies) == 3)


def test_5_each_validated():
    code, o = get("/api/drafts/chapter-099")
    vers = o.get("versions", []) if code == 200 else []
    check("T5 validation reports",
          len(vers) >= 3 and all(v.get("validation") for v in vers))


def test_6_each_consistency():
    code, o = get("/api/drafts/chapter-099")
    vers = o.get("versions", []) if code == 200 else []
    check("T6 consistency reports",
          len(vers) >= 3 and all(v.get("consistency") for v in vers))


def _sub(prefixes):
    prefixes = (prefixes,) if isinstance(prefixes, str) else prefixes
    return {k: v for k, v in REAL_SNAP.items() if k.startswith(prefixes)}


def test_7_drafts_not_canon():
    check("T7 canon untouched", snapshot("novel/canon") == _sub("novel/canon"))


def test_8_drafts_not_chapters():
    check("T8 chapters untouched", snapshot("novel/chapters") == _sub("novel/chapters"))


def test_9_select_version():
    code, o = chat("我選 chapter-099 的 v2")
    check("T9 select ok", code == 200 and "v2" in o.get("message", ""), o.get("message", "")[:60])


def test_10_revise_new_version():
    p = DRAFTS / TEST_CHAPTER / "v2.md"
    before = p.read_bytes() if p.is_file() else b""
    nums = [int(v[1:]) for v in _versions() if v[1:].isdigit()]
    expect = f"v{max(nums) + 1}" if nums else "v1"
    code, o = chat("星星不要這麼早暴露黑洞。")
    check("T10 revision reply", code == 200 and expect in o.get("message", ""),
          o.get("message", "")[:60])
    check("T10 new version exists", (DRAFTS / TEST_CHAPTER / (expect + ".md")).is_file())
    check("T10 v2 preserved", p.is_file() and p.read_bytes() == before)


def test_11_no_overwrite():
    vers = _versions()
    check("T11 versions intact",
          all(v in vers for v in ("v1", "v2", "v3")) and len(vers) == len(set(vers)),
          ",".join(vers))


def test_12_final_trigger_missing():
    code, o = chat("正式章節已確認，請存檔")
    check("T12 asks chapter", code == 200 and "指定" in o.get("message", ""))


def test_13_nondraft_no_sync():
    code, o = chat("正式章節已確認，請存檔 novel/drafts/chapter-099/v1.md")
    check("T13 drafts cannot sync", code == 200 and "拒絕" in o.get("message", ""),
          o.get("message", "")[:80])


def test_14_conflict_blocks_sync():
    code, o = chat("第59章已確定，請更新設定")
    check("T14 sync replied", code == 200, str(code))
    adop = sorted(ADOPTIONS.glob("059-adoption.json"))
    check("T14 adoption generated", len(adop) > 0)
    code2, o2 = chat("套用")
    check("T14 no auto-apply",
          snapshot("novel/canon", "novel/plot", "novel/review") == _sub(
              ("novel/canon", "novel/plot", "novel/review")),
          o2.get("message", "")[:80])


def test_15_proposed_provenance():
    adop = sorted(ADOPTIONS.glob("059-adoption.json"))
    check("T15 adoption exists", len(adop) > 0)
    if adop:
        data = json.loads(adop[0].read_text(encoding="utf-8"))
        check("T15 source_status kept",
              all("source_status" in c for c in data.get("changes", [])))


def test_16_inferred_provenance():
    adop = sorted(ADOPTIONS.glob("059-adoption.json"))
    if adop:
        data = json.loads(adop[0].read_text(encoding="utf-8"))
        inf = [c for c in data.get("changes", []) if c.get("source_status") == "INFERRED"]
        if inf:
            check("T16 inferred pending", all(c["approval"] in ("PENDING", "BLOCKED") for c in inf))
        else:
            check("T16 inferred pending", True, "no inferred candidates")
    else:
        check("T16 inferred pending", False, "no adoption file")


def test_17_ai_idea_gated():
    adop = sorted(ADOPTIONS.glob("059-adoption.json"))
    if adop:
        data = json.loads(adop[0].read_text(encoding="utf-8"))
        ais = [c for c in data.get("changes", []) if c.get("source_status") == "AI_IDEA"]
        check("T17 ai_idea gated",
              all(c["approval"] in ("PENDING", "BLOCKED") for c in ais),
              f"{len(ais)} ai_idea items")
    else:
        check("T17 ai_idea gated", False, "no adoption file")


def test_18_source_original():
    check("T18 source/original intact",
          snapshot("novel/source/original") == _sub("novel/source/original"))


def test_19_source_backup():
    check("T19 source/backup intact",
          snapshot("novel/source/backup") == _sub("novel/source/backup"))


def test_20_no_auto_log():
    logs = [p for p in ADOPTIONS.glob("*-adoption-log.json")]
    check("T20 no auto apply log", len(logs) == 0, f"{len(logs)} logs")


def test_21_api_health():
    code, o = get("/api/health")
    check("T21 health", code == 200 and o.get("ok") is True)


def test_22_path_traversal():
    for bad in ["/api/drafts/../..%2f.env", "/api/drafts/..%2f..%2fpackage.json",
                "/api/chapters/..%2f..%2f.env"]:
        code, _o = get(bad)
        check(f"T22 traversal {bad[-12:]}", code in (400, 404), f"code={code}")


def test_23_no_secrets():
    code, o = get("/")
    body = o if isinstance(o, str) else ""
    check("T23 root html", code == 200 and "星星小說 Agent" in body)
    for secret in ("LLM_API_KEY", "API_KEY", "sk-"):
        check(f"T23 no {secret}", secret not in body)


def test_24_chapters_api():
    code, o = get("/api/chapters")
    ids = [c["id"] for c in o.get("chapters", [])] if code == 200 else []
    check("T24 chapters listed", "059" in ids and "000" in ids, f"{len(ids)} chapters")
    latest = [c for c in (o.get("chapters", []) if code == 200 else []) if c.get("latest")]
    check("T24 latest flagged", len(latest) == 1 and latest[0]["id"] == "059")


def test_25_drafts_api():
    code, o = get("/api/drafts")
    chs = [d["chapter"] for d in o.get("drafts", [])] if code == 200 else []
    check("T25 drafts listed", TEST_CHAPTER in chs, ",".join(chs))


def test_26_chat_api():
    code, o = chat("hello")
    check("T26 chat shape",
          code == 200 and all(k in o for k in ("message", "status", "stages")))


def test_27_status_api():
    code, o = get("/api/status")
    check("T27 status shape",
          code == 200 and o.get("state") in (
              "IDLE", "THINKING", "CONTEXT_BUILD", "WRITING", "VALIDATING",
              "CONSISTENCY_CHECK", "WAITING_AUTHOR", "CANON_SYNC", "ERROR"))


def main() -> int:
    print("=== writing procedure + localhost UI tests ===")
    REAL_SNAP.update(snapshot(*PROTECTED))
    try:
        ADOPT_PRE.update(p.name for p in ADOPTIONS.iterdir())
    except Exception:
        pass
    start_server()
    cleanup_fixtures()
    try:
        test_1_write_trigger()
        test_2_discussion_no_trigger()
        test_3_context_built()
        test_4_three_drafts()
        test_5_each_validated()
        test_6_each_consistency()
        test_7_drafts_not_canon()
        test_8_drafts_not_chapters()
        test_9_select_version()
        test_10_revise_new_version()
        test_11_no_overwrite()
        test_12_final_trigger_missing()
        test_13_nondraft_no_sync()
        test_14_conflict_blocks_sync()
        test_15_proposed_provenance()
        test_16_inferred_provenance()
        test_17_ai_idea_gated()
        test_18_source_original()
        test_19_source_backup()
        test_20_no_auto_log()
        test_21_api_health()
        test_22_path_traversal()
        test_23_no_secrets()
        test_24_chapters_api()
        test_25_drafts_api()
        test_26_chat_api()
        test_27_status_api()
    finally:
        cleanup_fixtures()
        stop_server()
    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
