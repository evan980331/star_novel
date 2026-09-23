#!/usr/bin/env python3
"""Canon Adoption / Author Approval (phase 3E).

Change Set Generator + Explicit Approval Gate. Flow:

    Draft -> --generate -> Change Set (all PENDING, canon untouched)
          -> --approve/--reject/--approve-all (author decision)
          -> --apply (APPROVED only, version-locked, atomic) -> Adoption Log

    python novel/editor/canon_adopter.py novel/drafts/chapter-060-v1.md --generate
    python novel/editor/canon_adopter.py novel/adoptions/chapter-060-v1-adoption.json --approve A-001
    python novel/editor/canon_adopter.py novel/adoptions/chapter-060-v1-adoption.json --apply

Generate != Apply. Approve != Apply. Only --apply writes canon, and only
APPROVED items. Never touches novel/source/** or novel/chapters/**.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EDITOR_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = EDITOR_DIR.parent.parent

sys.path.insert(0, str(EDITOR_DIR))
import context_builder as cb  # noqa: E402 (alias roster)


def _load_hyphen(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EDITOR_DIR / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SCHEMA_VERSION = "1.0"

TARGET_FILE = {
    "CHARACTER": "novel/canon/characters.md",
    "ABILITY": "novel/canon/abilities.md",
    "WEAPON": "novel/canon/weapons.md",
    "FACTION": "novel/canon/factions.md",
    "LOCATION": "novel/canon/locations.md",
    "TERMINOLOGY": "novel/canon/terminology.md",
    "RELATIONSHIP": "novel/canon/relationships.md",
    "TIMELINE": "novel/canon/timeline.md",
    "PLOT": "novel/plot/current-arc.md",
    "FORESHADOWING": "novel/plot/foreshadowing.md",
}

# draft NEW-pattern -> (change type, canon file key)
NEW_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("CHARACTER", "characters", re.compile(r"新角色[「『:：\s]*([^」』\s，,。]{1,12})")),
    ("ABILITY", "abilities", re.compile(r"新能力[「『:：\s]*([^」』\s，,。]{1,12})")),
    ("WEAPON", "weapons", re.compile(r"新武器[「『:：\s]*([^」』\s，,。]{1,12})")),
    ("LOCATION", "locations", re.compile(r"新地點[「『:：\s]*([^」』\s，,。]{1,12})")),
    ("FACTION", "factions", re.compile(r"新勢力[「『:：\s]*([^」』\s，,。]{1,12})")),
    ("TERMINOLOGY", "terminology", re.compile(r"新術語[「『:：\s]*([^」』\s，,。]{1,12})")),
]

INFERRED_TYPE_HINTS = [
    ("CHARACTER", ["角色", "人物"]),
    ("ABILITY", ["能力", "技能", "神化", "神覺"]),
    ("WEAPON", ["武器"]),
    ("LOCATION", ["地點", "國家", "綠洲"]),
    ("FACTION", ["勢力", "家族", "組織"]),
    ("TERMINOLOGY", ["術語"]),
]

SAFE_ADD_TYPES = {"CHARACTER", "ABILITY", "WEAPON", "FACTION", "LOCATION",
                  "TERMINOLOGY", "RELATIONSHIP", "TIMELINE", "PLOT", "FORESHADOWING"}


class AdoptionError(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(root), capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(s: str) -> str:
    return cb.norm(s)


def keywords(text: str) -> list[str]:
    parts = [w for w in re.split(r"[／/、，,；;（）()\[\]【】「」『』\"' —–…·]+", text) if w]
    # drop pure-chapter refs and bare ASCII markers ([PROPOSED] etc. must
    # never count as conflict evidence by themselves)
    return [w for w in parts
            if len(w) >= 2
            and not re.fullmatch(r"#?\d+\.?$", w)
            and not re.fullmatch(r"[A-Z]+", w)]


def draft_frontmatter(draft_path: Path) -> tuple[dict, str]:
    dv = _load_hyphen("dv_adopt", "draft-validator.py")
    meta, body, err = dv.parse_frontmatter(read_text(draft_path))
    if err:
        raise AdoptionError(f"draft frontmatter invalid: {err}")
    return meta, body


def known_names() -> set[str]:
    names: set[str] = set()
    for _cat, table in cb.ENTITIES.items():
        for canon, als in table.items():
            names.add(canon)
            names.update(als)
    return names


def parse_sections(path: Path, levels: tuple[int, ...] = (2, 3)) -> list[dict]:
    items, cur = [], None
    for line in read_text(path).splitlines():
        m = re.match(r"^(#{2,4})\s+(.+?)\s*$", line.strip())
        if m and len(m.group(1)) in levels:
            if cur and "".join(cur["lines"]).strip():
                items.append(cur)
            cur = {"head": m.group(2).strip(), "level": len(m.group(1)), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur and "".join(cur["lines"]).strip():
        items.append(cur)
    return [{"head": it["head"], "text": "\n".join(it["lines"]).strip()} for it in items]


def parse_id_sections(path: Path, prefix: str) -> list[dict]:
    """Split on ID headers only (e.g. ## C-001); sub-headings stay in text."""
    pat = re.compile(r"^#{2,4}\s+(" + re.escape(prefix) + r"(?:-[ABC])?-?\d+)\b\s*(.*)$")
    items, cur = [], None
    for line in read_text(path).splitlines():
        m = pat.match(line.strip())
        if m:
            if cur and "".join(cur["lines"]).strip():
                items.append(cur)
            cur = {"id": m.group(1), "title": (m.group(2) or "").strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur and "".join(cur["lines"]).strip():
        items.append(cur)
    return [{"id": it["id"],
             "head": (it["id"] + " " + it["title"]).strip(),
             "title": it["title"],
             "text": "\n".join(it["lines"]).strip()} for it in items]


def review_conflicts(root: Path) -> list[dict]:
    return [{"id": s["id"], "title": s["head"], "text": s["text"]}
            for s in parse_id_sections(root / "novel" / "review" / "conflicts.md", "C")]


def conflict_status(text: str) -> str:
    return "[RESOLVED]" if "### 目前狀態\n[RESOLVED]" in text else "[UNRESOLVED]"


def resolved_via_decisions(root: Path) -> set[str]:
    """Conflict IDs recorded under 已確認 in author-decisions.md."""
    text = read_text(root / "novel" / "review" / "author-decisions.md")
    in_done = False
    out: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_done = "已確認" in s and "待確認" not in s
            continue
        if in_done:
            out.update(re.findall(r"C-\d+", s))
    return out


def proposed_sections(root: Path) -> list[dict]:
    return parse_id_sections(root / "novel" / "review" / "proposed.md", "P")


def inferred_sections(root: Path) -> list[dict]:
    return parse_id_sections(root / "novel" / "review" / "inferred.md", "I")


def ai_idea_phrases(root: Path) -> list[str]:
    phrases = []
    for p in (root / "novel" / "ideas").glob("*.md"):
        for line in read_text(p).splitlines():
            if "[AI IDEA]" in line:
                clean = re.sub(r"^-?\s*\[AI IDEA\]\s*", "", line.strip())
                for chunk in re.split(r"[，,。；;！？]", clean):
                    if len(chunk.strip()) >= 6:
                        phrases.append(chunk.strip())
    return phrases


def canon_headings(root: Path, rel: str) -> set[str]:
    return {s["head"] for s in parse_sections(root / rel)}


def snapshot(root: Path, dirs: tuple[str, ...]) -> dict[str, tuple[int, float]]:
    snap: dict[str, tuple[int, float]] = {}
    for rel in dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


PROTECTED_ALL = ("novel/source/original", "novel/source/backup", "novel/chapters",
                 "novel/canon", "novel/plot", "novel/review", "novel/adoptions")


# ---------------------------------------------------------------------------
# change-set generation (never writes canon)
# ---------------------------------------------------------------------------

def _conflict_hit(blob: str, conflicts: list[dict], resolved: set[str]) -> str | None:
    for c in conflicts:
        cid = c["id"]
        if cid in resolved or conflict_status(c["text"]) != "[UNRESOLVED]":
            continue
        if cid in blob:
            return cid
        for k in keywords(c["title"] + " " + c["text"][:600]):
            if len(k) >= 4 and k in blob:
                return cid
            if len(k) >= 4:
                for i in range(len(k) - 3):
                    w = k[i:i + 4]
                    # windows must carry real text (skip digit/punct fragments
                    # like "-001" that false-match IDs such as P-001)
                    if len(re.findall(r"[一-鿿A-Za-z]", w)) >= 2 and w in blob:
                        return cid
    return None


def generate(draft_path: Path, root: Path,
             out_dir: Path | None = None) -> tuple[Path, Path]:
    draft_path = draft_path.resolve()
    meta, body = draft_frontmatter(draft_path)
    try:
        draft_rel = draft_path.relative_to(root.resolve()).as_posix()
    except ValueError:
        draft_rel = draft_path.as_posix()

    conflicts = review_conflicts(root)
    resolved = resolved_via_decisions(root)
    names = known_names()
    canon_heads = {rel: canon_headings(root, rel) for rel in set(TARGET_FILE.values())}

    changes: list[dict] = []

    def add_change(ctype: str, action: str, target: str, field: str,
                   old: str | None, new: str, evidence: str,
                   source_status: str, blocked: str | None = None) -> None:
        changes.append({
            "id": f"A-{len(changes) + 1:03d}",
            "type": ctype, "action": action, "target": target, "field": field,
            "old_value": old, "new_value": new,
            "source": draft_rel, "evidence": evidence[:300],
            "confidence": "candidate",
            "approval": "BLOCKED" if blocked else "PENDING",
            "source_status": source_status,
            "blocked_reason": blocked,
        })

    def evidence_for(*needles: str) -> str:
        for sent in re.split(r"[。！？\n]+", body):
            if all(n and n in sent for n in needles if n):
                return sent.strip()
        return (needles[0] if needles else "")[:120]

    # 1. NEW-setting patterns in body
    for ctype, _fkey, pat in NEW_PATTERNS:
        for m in pat.finditer(body):
            name = m.group(1).strip("「『:： ")
            if not name:
                continue
            rel = TARGET_FILE[ctype]
            ev = evidence_for(name)
            blob = name + ev
            if name in names or name in canon_heads.get(rel, set()):
                # name collides with existing canon -> UPDATE, never silent add
                add_change(ctype, "UPDATE", name, "content", "(existing canon entry)",
                           ev or name, ev or name, "NEW_SETTING")
            else:
                add_change(ctype, "ADD", name, "content", None, ev or name,
                           ev or name, "NEW_SETTING")
            hit = _conflict_hit(blob, conflicts, resolved)
            if hit:
                changes[-1]["approval"] = "BLOCKED"
                changes[-1]["blocked_reason"] = f"conflict:{hit}"

    # 2. draft-declared proposed adoptions (explicit this-run adoption)
    prop_secs = {s["head"].split()[0]: s for s in proposed_sections(root)}
    for pid in meta.get("proposed_used", []) or []:
        sec = prop_secs.get(pid)
        title = sec["head"] if sec else pid
        raw = ""
        if sec:
            mline = re.search(r"原始內容：(.+)", sec["text"])
            raw = (mline.group(1).strip() if mline else title)[:300]
        # map to canon type by section path in proposed.md is complex;
        # default CHARACTER, refine by title hints below
        ctype = "CHARACTER"
        for t, hints in INFERRED_TYPE_HINTS:
            if any(h in title for h in hints):
                ctype = t
                break
        ev = evidence_for(pid, title.split()[0] if title else "")
        blob = pid + title + raw + ev
        hit = _conflict_hit(blob, conflicts, resolved)
        add_change(ctype, "ADD", title, "content", None, raw or title,
                   ev or title, "PROPOSED",
                   blocked=f"conflict:{hit}" if hit else None)

    # 3. draft-declared inferred items (author must confirm the inference)
    inf_secs = {s["head"].split()[0]: s for s in inferred_sections(root)}
    for iid in meta.get("inferred_used", []) or []:
        sec = inf_secs.get(iid)
        title = sec["head"] if sec else iid
        ctype = "PLOT"
        for t, hints in INFERRED_TYPE_HINTS:
            if any(h in title for h in hints):
                ctype = t
                break
        ev = evidence_for(iid)
        blob = iid + title + ev
        hit = _conflict_hit(blob, conflicts, resolved)
        add_change(ctype, "ADD", title, "content", None,
                   (sec["text"][:300] if sec else title), ev or title,
                   "INFERRED", blocked=f"conflict:{hit}" if hit else None)

    # 4. AI IDEA usage in body -> BLOCKED unless explicitly adopted in request
    req = str(meta.get("request", ""))
    explicit_ai = "採用" in req and "AI IDEA" in req
    for phrase in ai_idea_phrases(root):
        if phrase in body:
            add_change("PLOT", "ADD", f"AI IDEA: {phrase[:30]}", "content", None,
                       phrase, phrase, "AI_IDEA",
                       blocked=None if explicit_ai else "ai_idea")

    adoption_id = draft_path.stem + "-adoption"
    adoption = {
        "schema_version": SCHEMA_VERSION,
        "adoption_id": adoption_id,
        "draft": draft_rel,
        "draft_sha256": sha256_file(draft_path),
        "canon_version": git_head(root),
        "created_at": now_iso(),
        "status": "PENDING",
        "changes": changes,
        "conflicts": [{"id": c["id"], "status": conflict_status(c["text"])}
                      for c in conflicts],
        "summary": {},
    }
    adoption["summary"] = summarize(changes)

    out = out_dir.resolve() if out_dir else (root / "novel" / "adoptions").resolve()
    out.mkdir(parents=True, exist_ok=True)
    jpath = out / f"{adoption_id}.json"
    mpath = out / f"{adoption_id}.md"
    jpath.write_text(json.dumps(adoption, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    mpath.write_text(render_markdown(adoption, root), encoding="utf-8")
    return jpath, mpath


def summarize(changes: list[dict]) -> dict:
    return {
        "pending": sum(1 for c in changes if c["approval"] == "PENDING"),
        "approved": sum(1 for c in changes if c["approval"] == "APPROVED"),
        "rejected": sum(1 for c in changes if c["approval"] == "REJECTED"),
        "blocked": sum(1 for c in changes if c["approval"] == "BLOCKED"),
    }


def render_markdown(adoption: dict, root: Path) -> str:
    L = ["# Canon Adoption Review", "",
         f"Draft:\n{adoption['draft']}", "",
         f"Canon:\n{adoption['canon_version']}", ""]
    L += ["## Pending Changes", ""]
    if not adoption["changes"]:
        L.append("(no candidate changes)")
        L.append("")
    for c in adoption["changes"]:
        L += [f"### {c['id']}", f"Type: {c['type']}", f"Action: {c['action']}",
              f"Target: {c['target']}", f"Source status: {c['source_status']}", "",
              "Evidence:", c["evidence"] or "(none)", "", "Proposed Canon Change:",
              c["new_value"] or "(none)", "", "Approval:",
              c["approval"] + (f" ({c['blocked_reason']})" if c.get("blocked_reason") else ""),
              ""]
    L += ["## Conflicts", ""]
    for cf in adoption["conflicts"]:
        if cf["status"] == "[UNRESOLVED]":
            L += [f"{cf['id']}:", "Status:\nBLOCKED", "",
                  "Reason:\nAuthor decision required.", ""]
    s = adoption["summary"]
    L += ["## Summary", "", f"Pending: {s['pending']}",
          f"Approved: {s['approved']}", f"Rejected: {s['rejected']}",
          f"Blocked: {s['blocked']}", ""]
    L += ["> Generate ≠ Apply. Approve ≠ Apply. 只有 --apply 才會正式修改 Canon。", ""]
    _ = root
    return "\n".join(L)


# ---------------------------------------------------------------------------
# approval
# ---------------------------------------------------------------------------

def load_adoption(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AdoptionError(f"cannot load adoption file: {exc}")


def save_adoption(path: Path, adoption: dict, root: Path) -> None:
    adoption["summary"] = summarize(adoption["changes"])
    path.write_text(json.dumps(adoption, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    md = path.with_suffix(".md")
    if md.is_file() or True:
        md.write_text(render_markdown(adoption, root), encoding="utf-8")


def _lift_if_decided(change: dict, resolved: set[str]) -> None:
    br = change.get("blocked_reason") or ""
    if br.startswith("conflict:"):
        cid = br.split(":", 1)[1]
        if cid in resolved:
            change["approval"] = "PENDING"
            change["blocked_reason"] = None


def approve(path: Path, ids: list[str], root: Path) -> tuple[bool, str]:
    adoption = load_adoption(path)
    if adoption.get("status") == "APPLIED":
        return False, "adoption already APPLIED; refusing further approval changes."
    resolved = resolved_via_decisions(root)
    known = {c["id"] for c in adoption["changes"]}
    unknown = [i for i in ids if i not in known]
    if unknown:
        return False, f"unknown change ids: {','.join(unknown)}"
    for c in adoption["changes"]:
        if c["id"] not in ids:
            continue
        _lift_if_decided(c, resolved)
        if c["approval"] == "BLOCKED":
            br = c.get("blocked_reason") or ""
            if br.startswith("conflict:"):
                return False, (f"{c['id']} is BLOCKED by {br}; "
                               "author decision required in author-decisions.md.")
            # BLOCKED(ai_idea): explicit --approve IS the author approval
        c["approval"] = "APPROVED"
        if (c.get("blocked_reason") or "") == "ai_idea":
            c["blocked_reason"] = None
    save_adoption(path, adoption, root)
    return True, f"approved: {','.join(ids)}"


def reject(path: Path, ids: list[str], root: Path) -> tuple[bool, str]:
    adoption = load_adoption(path)
    if adoption.get("status") == "APPLIED":
        return False, "adoption already APPLIED; refusing further changes."
    known = {c["id"] for c in adoption["changes"]}
    unknown = [i for i in ids if i not in known]
    if unknown:
        return False, f"unknown change ids: {','.join(unknown)}"
    for c in adoption["changes"]:
        if c["id"] in ids:
            c["approval"] = "REJECTED"
    save_adoption(path, adoption, root)
    return True, f"rejected: {','.join(ids)}"


def approve_all(path: Path, root: Path) -> tuple[bool, str]:
    adoption = load_adoption(path)
    if adoption.get("status") == "APPLIED":
        return False, "adoption already APPLIED."
    resolved = resolved_via_decisions(root)
    live = [c for c in adoption["changes"] if c["approval"] != "REJECTED"]
    for c in live:
        _lift_if_decided(c, resolved)
    blockers = []
    for c in live:
        if (c.get("blocked_reason") or "").startswith("conflict:"):
            blockers.append(f"{c['id']} unresolved conflict")
        if c.get("source_status") in ("PROPOSED", "INFERRED", "AI_IDEA"):
            blockers.append(f"{c['id']} unconfirmed {c['source_status']}")
        if c["action"] != "ADD" or c["type"] not in SAFE_ADD_TYPES:
            blockers.append(f"{c['id']} not a safe ADD type")
        if c["approval"] == "BLOCKED":
            blockers.append(f"{c['id']} blocked")
    if blockers:
        return False, "--approve-all refused: " + "; ".join(blockers[:8])
    # draft must be ERROR-free
    draft_p = root / adoption["draft"]
    if draft_p.is_file():
        cc = _load_hyphen("cc_adopt", "consistency_checker.py")
        rep = cc.Checker(draft_p, None).run(cc.snapshot())
        if rep["summary"]["errors"]:
            return False, "--approve-all refused: draft has consistency ERRORs."
    for c in live:
        if c["approval"] == "PENDING":
            c["approval"] = "APPROVED"
    save_adoption(path, adoption, root)
    done = [c["id"] for c in live if c["approval"] == "APPROVED"]
    return True, f"approved: {','.join(done)}" if done else "nothing to approve"


# ---------------------------------------------------------------------------
# apply (APPROVED only, version-locked, atomic)
# ---------------------------------------------------------------------------

def _render_add_canon(change: dict, date: str) -> str:
    return (f"\n\n### {change['target']} [ADOPTED {date}]\n\n"
            f"- {change['new_value']}\n"
            f"- Source: {change['source']} "
            f"(adoption change {change['id']}, source_status {change['source_status']})\n")


def _render_add_plot(change: dict, date: str) -> str:
    return (f"\n\n### [ADOPTED {date}] {change['target']}\n\n"
            f"{change['new_value']}\n\n"
            f"Source: {change['source']} "
            f"(adoption change {change['id']}, source_status {change['source_status']})\n")


def _split_section(text: str, head: str) -> tuple[str, str, str] | None:
    """Split markdown into (before, section, after) for a unique heading."""
    lines = text.splitlines(keepends=True)
    idx = [i for i, l in enumerate(lines)
           if re.match(r"^#{2,4}\s+" + re.escape(head) + r"\s*$", l.strip())]
    if len(idx) != 1:
        return None
    i = idx[0]
    m = re.match(r"^(#{2,4})\s+", lines[i].strip())
    level = len(m.group(1)) if m else 2
    j = i + 1
    while j < len(lines):
        m2 = re.match(r"^(#{2,4})\s+", lines[j].strip())
        if m2 and len(m2.group(1)) <= level:
            break
        j += 1
    return "".join(lines[:i]), "".join(lines[i:j]), "".join(lines[j:])


def compute_new_texts(adoption: dict, root: Path, date: str) -> dict[str, str]:
    """Render every approved change in memory. Raises AdoptionError on any problem."""
    approved = [c for c in adoption["changes"] if c["approval"] == "APPROVED"]
    if not approved:
        raise AdoptionError("nothing APPROVED to apply.")
    for c in approved:
        if c["action"] not in ("ADD", "UPDATE", "DEPRECATE"):
            raise AdoptionError(f"{c['id']}: invalid action {c['action']}; refusing.")
        if c["type"] not in TARGET_FILE:
            raise AdoptionError(f"{c['id']}: invalid type {c['type']}; refusing.")
    staged: dict[str, str] = {}
    for c in approved:
        rel = TARGET_FILE[c["type"]]
        if rel.startswith("novel/chapters") or rel.startswith("novel/source"):
            raise AdoptionError(f"{c['id']}: forbidden target {rel}.")
        text = staged.get(rel)
        if text is None:
            text = read_text(root / rel)
            if not text and not (root / rel).is_file():
                raise AdoptionError(f"target file missing: {rel}")
        if c["action"] == "ADD":
            block = _render_add_canon(c, date) if rel.startswith("novel/canon/") \
                else _render_add_plot(c, date)
            if c["target"] in text and c["type"] in ("CHARACTER", "ABILITY", "WEAPON"):
                raise AdoptionError(
                    f"{c['id']}: target already present; refusing silent duplicate.")
            text = text.rstrip("\n") + "\n" + block
        elif c["action"] == "UPDATE":
            parts = _split_section(text, c["target"])
            if parts is None:
                raise AdoptionError(
                    f"{c['id']}: UPDATE target heading not unique/found: {c['target']}.")
                continue
            before, _old, after = parts
            new_sec = (f"### {c['target']} [ADOPTED {date}]\n\n"
                       f"- {c['new_value']}\n"
                       f"- Supersedes previous content (see adoption log).\n"
                       f"- Source: {c['source']} (adoption change {c['id']})\n")
            text = before + new_sec + after
        else:  # DEPRECATE
            parts = _split_section(text, c["target"])
            if parts is None:
                raise AdoptionError(
                    f"{c['id']}: DEPRECATE target heading not unique/found.")
                continue
            before, old, after = parts
            old = old.rstrip("\n") + (f"\n- [DEPRECATED {date}] {c['new_value']} "
                                      f"(adoption change {c['id']})\n")
            text = before + old + after
        staged[rel] = text
    return staged


def apply_adoption(path: Path, root: Path) -> tuple[bool, str]:
    adoption = load_adoption(path)
    if adoption.get("status") == "APPLIED":
        return False, "already APPLIED; refusing repeat apply."
    approved = [c for c in adoption["changes"] if c["approval"] == "APPROVED"]
    if not approved:
        return False, "nothing APPROVED to apply."
    if any(c["approval"] == "BLOCKED" and (c.get("blocked_reason") or "").startswith("conflict:")
           for c in adoption["changes"]):
        # blocked-conflict items are simply not applied; but if an APPROVED
        # item touches a *currently* unresolved conflict -> refuse
        pass
    if git_head(root) != adoption.get("canon_version"):
        return False, (f"ERROR CANON_VERSION_CHANGED: adoption built at "
                       f"{adoption.get('canon_version')}, HEAD is now {git_head(root)}.")

    draft_p = root / adoption["draft"]
    if not draft_p.is_file() or sha256_file(draft_p) != adoption.get("draft_sha256"):
        return False, "ERROR DRAFT_CHANGED: source draft missing or modified."

    # live conflict re-check on approved items
    conflicts = review_conflicts(root)
    resolved = resolved_via_decisions(root)
    for c in approved:
        blob = c["target"] + c.get("evidence", "") + (c.get("new_value", "") or "")
        hit = _conflict_hit(blob, conflicts, resolved)
        if hit:
            return False, (f"ERROR: {c['id']} touches unresolved {hit}; "
                           "author decision required.")

    # consistency must be ERROR-free
    cc = _load_hyphen("cc_adopt", "consistency_checker.py")
    rep = cc.Checker(draft_p, None).run(cc.snapshot())
    if rep["summary"]["errors"]:
        return False, "ERROR: draft has consistency ERRORs; refusing apply."

    before_snap = snapshot(root, PROTECTED_ALL)
    canon_before = {rel: sha256_file(root / rel)
                    for rel in {TARGET_FILE[c["type"]] for c in approved}
                    if (root / rel).is_file()}
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        staged = compute_new_texts(adoption, root, date)
    except AdoptionError as exc:
        return False, f"ERROR: {exc}"

    # atomic: stage to temp files first, then replace
    tmp_files: dict[str, tuple[str, str]] = {}
    try:
        for rel, text in staged.items():
            dest = root / rel
            fd, tmpp = tempfile.mkstemp(dir=str(dest.parent), suffix=".adopttmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            tmp_files[rel] = (tmpp, text)
        # verify staged content parses back and contains markers
        for rel, (tmpp, _text) in tmp_files.items():
            back = Path(tmpp).read_text(encoding="utf-8")
            if "[ADOPTED " not in back and "[DEPRECATED " not in back:
                raise AdoptionError(f"staged {rel} failed verification.")
        for rel, (tmpp, _text) in tmp_files.items():
            os.replace(tmpp, root / rel)
    except Exception as exc:
        for _rel, (tmpp, _text) in tmp_files.items():
            try:
                if os.path.exists(tmpp):
                    os.remove(tmpp)
            except Exception:
                pass
        return False, f"ERROR during atomic apply, canon untouched: {exc}"

    adoption["status"] = "APPLIED"
    save_adoption(path, adoption, root)

    after_snap = snapshot(root, PROTECTED_ALL)
    changed = {k for k in set(before_snap) | set(after_snap)
               if before_snap.get(k) != after_snap.get(k)}
    try:
        adopt_rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        adopt_rel = ""
    expected = {TARGET_FILE[c["type"]] for c in approved} | {adopt_rel} | \
        {adopt_rel[:-5] + ".md" if adopt_rel.endswith(".json") else ""}
    expected.discard("")
    forbidden = [k for k in changed
                 if k.startswith("novel/chapters") or k.startswith("novel/source")]
    if forbidden:
        return False, f"ERROR: forbidden files touched: {forbidden}"
    unexpected = [k for k in changed if k not in expected]
    if unexpected:
        return False, f"ERROR: unexpected files changed: {unexpected}"

    log = {
        "adoption_id": adoption["adoption_id"],
        "draft": adoption["draft"],
        "canon_before": adoption.get("canon_version"),
        "canon_after": git_head(root),
        "canon_files_before": canon_before,
        "canon_files_after": {rel: sha256_file(root / rel) for rel in canon_before},
        "approved_changes": [c["id"] for c in approved],
        "rejected_changes": [c["id"] for c in adoption["changes"]
                             if c["approval"] == "REJECTED"],
        "timestamp": now_iso(),
        "status": "APPLIED",
    }
    log_dir = root / "novel" / "adoptions"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"{stamp}-adoption-log.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return True, f"APPLIED {len(approved)} change(s); log: {log_path.name}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canon Adoption / Author Approval Gate.")
    ap.add_argument("path")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--approve", nargs="*", default=None)
    ap.add_argument("--reject", nargs="*", default=None)
    ap.add_argument("--approve-all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = Path(args.root)
    try:
        if args.generate:
            jpath, mpath = generate(Path(args.path), root,
                                    Path(args.out_dir) if args.out_dir else None)
            print(f"adoption written: {jpath}")
            print(f"report written: {mpath}")
            print("canon untouched. Generate != Apply.")
            return 0
        apath = Path(args.path)
        if args.approve is not None:
            ok, msg = approve(apath, args.approve, root)
            print(msg)
            return 0 if ok else 1
        if args.reject is not None:
            ok, msg = reject(apath, args.reject, root)
            print(msg)
            return 0 if ok else 1
        if args.approve_all:
            ok, msg = approve_all(apath, root)
            print(msg)
            return 0 if ok else 1
        if args.apply:
            ok, msg = apply_adoption(apath, root)
            print(msg)
            return 0 if ok else 1
        print("specify one of: --generate, --approve, --reject, --approve-all, --apply")
        return 2
    except AdoptionError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
