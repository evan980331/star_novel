#!/usr/bin/env python3
"""Draft Validator (phase 3C): draft -> Validation Report.

    python novel/editor/draft-validator.py novel/drafts/chapter-060-001.md

Read-only: never modifies canon, chapters, or the draft itself.
New settings are reported as [NEW_SETTING] (author confirmation required),
NOT as failures. Exit 0 = no failures, 1 = failures found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EDITOR_DIR = Path(__file__).resolve().parent
ROOT = EDITOR_DIR.parent.parent
DRAFTS_DIR = ROOT / "novel" / "drafts"

sys.path.insert(0, str(EDITOR_DIR))
import context_builder as cb  # noqa: E402


def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Minimal YAML-subset parser for our frontmatter. Returns (meta, body, error)."""
    if not text.startswith("---"):
        return {}, text, "missing frontmatter delimiter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text, "unclosed frontmatter"
    raw, body = parts[1], parts[2]
    meta: dict = {}
    cur_key: str | None = None
    cur_dict: dict | None = None
    for lineno, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            cur_key = m.group(1)
            cur_dict = None
            val = m.group(2).strip()
            if val == "":
                meta[cur_key] = []
            else:
                meta[cur_key] = _scalar(val)
            continue
        m2 = re.match(r"^  - (.*)$", line)
        if m2 and cur_key is not None and isinstance(meta.get(cur_key), list):
            item = m2.group(1).strip()
            mm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", item)
            if mm:
                cur_dict = {mm.group(1): _scalar(mm.group(2))}
                meta[cur_key].append(cur_dict)
            else:
                cur_dict = None
                meta[cur_key].append(_scalar(item))
            continue
        m3 = re.match(r"^    ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m3 and cur_dict is not None:
            cur_dict[m3.group(1)] = _scalar(m3.group(2))
            continue
        return {}, text, f"bad syntax at frontmatter line {lineno}"
    return meta, body, ""


def _flow_list(val: str) -> list[str] | None:
    val = val.strip()
    if not (val.startswith("[") and val.endswith("]")):
        return None
    inner = val[1:-1].strip()
    if not inner:
        return []
    items = re.findall(r'"((?:[^"\\]|\\.)*)"', inner)
    return [i.replace('\\"', '"') for i in items]


def _scalar(val: str) -> str | bool | list:
    val = val.strip()
    if val == "true":
        return True
    if val == "false":
        return False
    flow = _flow_list(val)
    if flow is not None:
        return flow
    if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if len(val) >= 2 and val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    return val


def _keywords(title: str) -> list[str]:
    parts = [w for w in re.split(r"[／/、，,（）()\[\] ]+", title) if w]
    # drop pure chapter refs like #068; keep substance
    return [w for w in parts if len(w) >= 2 and not re.fullmatch(r"#?\d+", w)]


def _mentioned(keys: list[str], pid: str, body: str) -> bool:
    if pid and pid in body:
        return True
    hits = [k for k in keys if k and k in body]
    if any(len(k) >= 4 for k in hits):
        return True
    return len(hits) >= 2


REQUIRED_KEYS = ["draft_id", "target", "request", "request_type", "status",
                 "content", "needs_author_decision", "warnings", "conflicts_used",
                 "proposed_used", "inferred_used", "source_chapters", "source_trace"]


def known_roster() -> set[str]:
    roster: set[str] = set()
    for _cat, table in cb.ENTITIES.items():
        for canon, als in table.items():
            roster.add(canon)
            roster.update(als)
    return roster


def review_titles() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(proposed [(id, title)], conflicts [(id, title)]) from review files."""
    prop, conf = [], []
    for fname, prefix, dest in [("proposed.md", "P", prop), ("conflicts.md", "C", conf)]:
        cur = None
        for line in (ROOT / "novel" / "review" / fname).read_text(
                encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^#{2,3}\s+(" + re.escape(prefix) + r"(?:-[ABC])?-?\d+)\b\s*(.*)$",
                         line.strip())
            if m:
                if cur:
                    dest.append(cur)
                cur = (m.group(1), (m.group(2) or "").strip())
        if cur:
            dest.append(cur)
    return prop, conf


NEW_PATTERNS = [("character", re.compile(r"新角色[「『:：\s]*([^」』\s，,。]{1,12})")),
                ("ability", re.compile(r"新能力[「『:：\s]*([^」』\s，,。]{1,12})")),
                ("weapon", re.compile(r"新武器[「『:：\s]*([^」』\s，,。]{1,12})"))]


def validate(path: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    """Returns (failures, warnings, new_settings, infos)."""
    failures: list[str] = []
    warnings: list[str] = []
    new_settings: list[str] = []
    infos: list[str] = []

    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    if DRAFTS_DIR.resolve() not in resolved.parents:
        return ([f"draft outside novel/drafts/: {path}"], [], [], [])

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return ([f"cannot read draft: {exc}"], [], [], [])

    meta, body, err = parse_frontmatter(text)
    if err:
        return ([f"frontmatter: {err}"], [], [], [])
    infos.append("frontmatter parsed")

    # 1. metadata complete (content lives in body; schema key maps to body)
    full = dict(meta)
    full["content"] = body.strip()
    for k in REQUIRED_KEYS:
        if k not in full or full[k] is None:
            failures.append(f"metadata missing: {k}")
    if not failures:
        infos.append("metadata complete")

    # source_trace shape (source may be a JSON-encoded string)
    trace = meta.get("source_trace", [])
    trace_ok = isinstance(trace, list)
    if trace_ok:
        for entry in trace:
            if not isinstance(entry, dict) or not {"type", "name", "source"} <= set(entry):
                trace_ok = False
                break
            src = entry["source"]
            if isinstance(src, str):
                try:
                    entry["source"] = json.loads(src)
                except Exception:
                    trace_ok = False
                    break
    if trace_ok:
        infos.append(f"source_trace ok ({len(trace)} entries)")
    else:
        failures.append("bad source_trace")

    # status must stay DRAFT
    if meta.get("status") != "DRAFT":
        failures.append(f"status is not DRAFT: {meta.get('status')}")

    # target / chapter refs
    target = str(meta.get("target", ""))
    tm = re.match(r"chapter-(\d+)", target)
    target_num = int(tm.group(1)) if tm else None
    refs: set[int] = set()
    for pat in [re.compile(r"#\s*(\d+)"), re.compile(r"第\s*(\d+)\s*章"),
                re.compile(r"chapter\s*(\d+)", re.IGNORECASE)]:
        for m in pat.finditer(body):
            try:
                refs.add(int(m.group(1)))
            except ValueError:
                pass
    for n in sorted(refs):
        if n > 59 and n != target_num:
            failures.append(f"references nonexistent Chapter #{n}")
    for s in meta.get("source_chapters", []) or []:
        try:
            sn = int(str(s))
        except ValueError:
            failures.append(f"bad source_chapter: {s}")
            continue
        if sn > 59 or not (ROOT / "novel" / "chapters" / f"{sn:03d}.md").is_file():
            failures.append(f"source chapter missing: {s}")
    if not any(f.startswith("references nonexistent") or f.startswith("source chapter")
               for f in failures):
        infos.append("chapter refs ok")

    # entities: unknown -> [NEW_SETTING], never FAIL
    roster = known_roster()
    for ent in meta.get("entities_used", []) or []:
        if ent not in roster:
            new_settings.append(f"角色/實體：{ent}（metadata entities_used 未見於 Canon 名錄）")
    for kind, pat in NEW_PATTERNS:
        for m in pat.finditer(body):
            name = m.group(1).strip("「『:： ")
            if name and name not in roster:
                new_settings.append(f"{kind}：{name}（正文新設定）")
    if new_settings:
        warnings.append(f"{len(new_settings)} [NEW_SETTING] item(s): 作者確認後才能加入 Canon。")
    else:
        infos.append("no new settings")

    # proposed usage must stay marked
    prop, conf = review_titles()
    for pid, title in prop:
        keys = _keywords(title)
        if _mentioned(keys, pid, body) and not ("[PROPOSED]" in body or pid in body):
            warnings.append(f"unmarked [PROPOSED] usage suspected: {pid} {title[:20]}")
        if pid in (meta.get("proposed_used", []) or []):
            infos.append(f"proposed adopted for this run only: {pid}（未寫入 Canon）")

    # conflict involvement requires NEEDS_AUTHOR_DECISION
    for cid, title in conf:
        keys = _keywords(title)
        if _mentioned(keys, cid, body) and "[NEEDS_AUTHOR_DECISION]" not in body:
            warnings.append(
                f"[CONFLICT] {cid} involved without [NEEDS_AUTHOR_DECISION]")
    if meta.get("needs_author_decision") and "[NEEDS_AUTHOR_DECISION]" not in body \
            and "[INSUFFICIENT_CONTEXT]" not in body:
        warnings.append("needs_author_decision=true but no marker block in body")

    return failures, warnings, new_settings, infos


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("usage: draft-validator.py <draft.md>")
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    failures, warnings, new_settings, infos = validate(Path(argv[0]))
    print(f"=== Validation Report: {argv[0]} ===")
    for i in infos:
        print(f"INFO: {i}")
    for n in new_settings:
        print(f"[NEW_SETTING] {n}")
    for w in warnings:
        print(f"WARN: {w}")
    for f in failures:
        print(f"FAIL: {f}")
    print(f"=== RESULT: {len(failures)} failures, "
          f"{len(warnings)} warnings, {len(new_settings)} new settings ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
