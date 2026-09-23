#!/usr/bin/env python3
"""Consistency / Quality Gate (phase 3D).

Deterministic checker: Draft -> JSON/Markdown Report -> PASS/WARNING/ERROR
-> author review. Check-only: never modifies canon, chapters, review, plot,
source, or the draft itself.

    python novel/editor/consistency_checker.py novel/drafts/chapter-060-v1.md --json
    python novel/editor/consistency_checker.py novel/drafts/chapter-060-v1.md --markdown
    python novel/editor/consistency_checker.py <draft> --json --output <path>
    python novel/editor/consistency_checker.py <draft> --strict

Exit codes: normal mode ERROR->1 else 0; --strict also maps WARNING->1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

EDITOR_DIR = Path(__file__).resolve().parent
ROOT = EDITOR_DIR.parent.parent

sys.path.insert(0, str(EDITOR_DIR))
import context_builder as cb  # noqa: E402 (entity/alias roster source)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "dv_mod_3d", EDITOR_DIR / "draft-validator.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROTECTED_DIRS = ("novel/source/original", "novel/source/backup",
                  "novel/chapters", "novel/canon", "novel/plot", "novel/review")

SCHEMA_VERSION = "1.0"

# Exclusive abilities/weapons and their canon owners (mirrors canon files;
# every issue cites the source file, checker invents no settings).
EXCLUSIVE_ABILITY_OWNER = {
    "發散": ("星星", "novel/canon/abilities.md"),
    "收斂": ("星星", "novel/canon/abilities.md"),
    "黑洞": ("星星", "novel/canon/abilities.md"),
    "六星飛環": ("星星", "novel/canon/weapons.md"),
    "星之劍": ("星星", "novel/canon/weapons.md"),
    "星之弓": ("星星", "novel/canon/weapons.md"),
    "星之盾": ("星星", "novel/canon/weapons.md"),
    "時差流星": ("星星", "novel/canon/abilities.md"),
}
EXCLUSIVE_WEAPON_OWNER = {
    "星之劍": ("星星", "novel/canon/weapons.md"),
    "星之弓": ("星星", "novel/canon/weapons.md"),
    "星之盾": ("星星", "novel/canon/weapons.md"),
    "六星飛環": ("星星", "novel/canon/weapons.md"),
    "彗星手套": ("星星", "novel/canon/weapons.md"),
    "流星手套": ("星星", "novel/canon/weapons.md"),
    "重劍": ("星星", "novel/canon/weapons.md"),
    "觀測之鏡": ("奧法辛", "novel/canon/terminology.md"),
}
STAGE_WORDS = ["神覺", "絕對發散", "絕對收斂", "奇點"]
ACTIVATE_WORDS = ["開啟", "進入", "施展", "用出", "爆發", "啟動", "解放", "使出"]
DEATH_WORDS = ["戰死", "死亡", "身亡", "死去", "隕落", "斃命", "已死",
               "去世", "喪生", "陣亡"]
DEATH_CONTEXT = ["死", "亡", "屍", "骸", "追悼", "回憶", "曾經", "傳說", "聽說", "夢", "悼念"]
MOVE_WORDS = ["前往", "抵達", "傳送", "移動", "趕往", "出發", "飛行", "趕到", "來到", "回到", "離開"]
HEDGE_WORDS = ["可能", "或許", "推測", "似乎", "應該", "也許", "疑似", "傳聞", "據說"]

SENT_SPLIT = re.compile(r"[。！？\n]+")
META_LINE = re.compile(r"^\s*(\[MOCK DRAFT\]|Entities|Context items|Request|Task type|本草稿|正式寫作)")


def story_sentences(body: str) -> list[str]:
    """Body sentences minus metadata echo lines (mock headers, entity lists)."""
    return [s for s in SENT_SPLIT.split(body)
            if s.strip() and not META_LINE.match(s.strip())]
CHAPTER_RES = [re.compile(r"#\s*(\d+)"), re.compile(r"第\s*(\d+)\s*章"),
               re.compile(r"chapter\s*(\d+)", re.IGNORECASE)]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def snapshot() -> dict[str, tuple[int, float]]:
    snap: dict[str, tuple[int, float]] = {}
    for rel in PROTECTED_DIRS:
        for p in (ROOT / rel).rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[p.relative_to(ROOT).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def keywords(title: str) -> list[str]:
    parts = [w for w in re.split(r"[／/、，,；;（）()\[\]【】「」『』\"' —–…·]+", title) if w]
    return [w for w in parts if len(w) >= 2 and not re.fullmatch(r"#?\d+\.?$", w)]


def title_hit(title: str, pid: str, body: str) -> bool:
    """Long CJK titles: full-chunk match (len>=4) or any 5-char window."""
    if pid and pid in body:
        return True
    for k in keywords(title):
        if len(k) >= 4 and k in body:
            return True
        if len(k) >= 5:
            for i in range(len(k) - 4):
                if k[i:i + 5] in body:
                    return True
    return False


def mentioned(keys: list[str], pid: str, body: str) -> bool:
    if pid and pid in body:
        return True
    hits = [k for k in keys if k and k in body]
    if any(len(k) >= 4 for k in hits):
        return True
    return len(hits) >= 2


def roster() -> tuple[set[str], dict[str, str]]:
    """(all known names/aliases, alias->canonical)."""
    names: set[str] = set()
    canon_of: dict[str, str] = {}
    for _cat, table in cb.ENTITIES.items():
        for canon, als in table.items():
            names.add(canon)
            canon_of[canon] = canon
            for a in als:
                names.add(a)
                canon_of.setdefault(a, canon)
    return names, canon_of


def death_roster() -> list[tuple[str, str, str]]:
    """Derive (name, level, evidence) from explicit death records.

    Character entities only. Two deterministic sources (no free-text
    co-occurrence, which misattributes killer to victim):
    1. characters.md: death wording inside a character's own ## section.
    2. timeline/current-arc lines: NAME immediately followed by a death
       word (e.g. X已戰死 / X死亡), i.e. strict adjacency.
    """
    chars: dict[str, list[str]] = cb.ENTITIES.get("character", {})
    names = sorted({n for c, als in chars.items() for n in [c, *als]},
                   key=len, reverse=True)
    out: list[tuple[str, str, str]] = []

    def level_of(line: str) -> str:
        return "WARNING" if ("[INFERRED]" in line or "[PROPOSED]" in line) else "ERROR"

    sections: list[tuple[str, list[str]]] = []
    cur: tuple[str, list[str]] | None = None
    for line in read_text(ROOT / "novel" / "canon" / "characters.md").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if cur and "".join(cur[1]).strip():
                sections.append(cur)
            cur = (m.group(1), [])
        elif cur is not None:
            cur[1].append(line)
    if cur and "".join(cur[1]).strip():
        sections.append(cur)
    for heading, lines in sections:
        owner = next((n for n in names if n in heading and len(n) >= 2), "")
        if not owner:
            continue
        for line in lines:
            if any(w in line for w in DEATH_WORDS):
                out.append((owner, level_of(line), line.strip()[:120]))
                break

    adj = "(" + "|".join(re.escape(n) for n in names if len(n) >= 2) + ")"
    pat = re.compile(adj + r"(被|已|遭|經|因)?(" + "|".join(DEATH_WORDS) + r")")
    for rel in ["novel/canon/timeline.md", "novel/plot/current-arc.md"]:
        for line in read_text(ROOT / rel).splitlines():
            m = pat.search(line)
            if m:
                out.append((m.group(1), level_of(line), line.strip()[:120]))
    seen: dict[str, tuple[str, str, str]] = {}
    for n, lv, ev in out:
        if n not in seen or (seen[n][1] == "WARNING" and lv == "ERROR"):
            seen[n] = (n, lv, ev)
    return list(seen.values())


def canon_location_assertions() -> list[tuple[str, str, str]]:
    """(character, location, evidence) from explicit status-table rows only.

    Only markdown table rows of the form `| **NAME** | ... |` count as an
    explicit location record; free-text co-occurrence does not.
    """
    text = read_text(ROOT / "novel" / "plot" / "current-arc.md")
    chars = set(cb.ENTITIES.get("character", {}).keys())
    seen_keys: set[tuple[str, str]] = set()
    loc_aliases: dict[str, str] = {}
    for canon, als in cb.ENTITIES.get("location", {}).items():
        for a in als:
            loc_aliases[a] = canon
    out = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|(.*)\|$", line.strip())
        if not m:
            continue
        name, rest = m.group(1).strip(), m.group(2)
        if name not in chars:
            continue
        for alias, loc in loc_aliases.items():
            if alias in rest:
                key = (name, loc)
                if key not in seen_keys:
                    seen_keys.add(key)
                    out.append((name, loc, line.strip()[:120]))
    return out


def review_items(fname: str, prefix: str) -> list[dict]:
    items, cur = [], None
    for line in read_text(ROOT / "novel" / "review" / fname).splitlines():
        m = re.match(r"^#{2,3}\s+(" + re.escape(prefix) + r"(?:-[ABC])?-?\d+)\b\s*(.*)$",
                     line.strip())
        if m:
            if cur and "".join(cur["lines"]).strip():
                items.append(cur)
            cur = {"id": m.group(1), "title": (m.group(2) or "").strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur and "".join(cur["lines"]).strip():
        items.append(cur)
    return [{"id": it["id"], "title": it["title"],
             "text": "\n".join(it["lines"]).strip()} for it in items]


def ai_idea_phrases() -> list[str]:
    phrases = []
    for p in (ROOT / "novel" / "ideas").glob("*.md"):
        for line in read_text(p).splitlines():
            if "[AI IDEA]" in line:
                clean = re.sub(r"^-?\s*\[AI IDEA\]\s*", "", line.strip())
                for chunk in re.split(r"[，,。；;！？]", clean):
                    if len(chunk.strip()) >= 6:
                        phrases.append(chunk.strip())
    return phrases


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class Checker:
    def __init__(self, draft_path: Path, context: dict | None = None):
        self.draft_path = draft_path
        self.dv = _load_validator()
        self.meta, self.body, self.perr = self.dv.parse_frontmatter(
            read_text(draft_path))
        self.context = context
        self.issues: list[dict] = []
        self.checks: list[dict] = []
        self._n = 0

    def add(self, severity: str, category: str, message: str,
            evidence: str, source: str, recommendation: str) -> None:
        self._n += 1
        self.issues.append({
            "id": f"C3D-{self._n:03d}", "severity": severity, "category": category,
            "message": message, "evidence": evidence[:300], "source": source,
            "recommendation": recommendation,
        })

    def record(self, cid: str, name: str, result: str) -> None:
        self.checks.append({"id": cid, "name": name, "result": result})

    # -- individual checks -------------------------------------------------
    def check_unknown_entity(self) -> None:
        names, _ = roster()
        found: list[str] = []
        for ent in (self.meta.get("entities_used") or []):
            if ent not in names:
                found.append(f"實體：{ent}（metadata 未見於 Canon 名錄）")
        for kind, pat in self.dv.NEW_PATTERNS:
            for m in pat.finditer(self.body):
                nm = m.group(1).strip("「『:： ")
                if nm and nm not in names:
                    found.append(f"{kind}：{nm}")
        if found:
            for f in found:
                self.add("WARNING", "UNKNOWN_ENTITY",
                         f"Draft introduces unknown entity: {f}",
                         f, "novel/canon/*.md",
                         "[NEW_SETTING] Author confirmation required before canon adoption.")
            self.record("C3D-001", "Unknown Entity", "WARNING")
        else:
            self.record("C3D-001", "Unknown Entity", "PASS")

    def check_character_status(self) -> None:
        worst = "PASS"
        for name, level, ev in death_roster():
            for sent in story_sentences(self.body):
                if name in sent and not any(w in sent for w in DEATH_CONTEXT):
                    self.add(level, "CHARACTER_STATUS",
                             f"Possibly-deceased character reappears: {name}",
                             sent.strip()[:120],
                             "novel/canon/characters.md, novel/canon/timeline.md",
                             "作者確認該角色是否確實存活；不得忽視既有死亡紀錄。")
                    worst = "ERROR" if level == "ERROR" else (
                        "WARNING" if worst == "PASS" else worst)
                    break
        self.record("C3D-002", "Character Status", worst)

    def check_character_location(self) -> None:
        assertions = canon_location_assertions()
        hit = False
        for char, loc, ev in assertions:
            for sent in story_sentences(self.body):
                if char in sent and loc in sent:
                    continue
                # draft asserts char at a *different* known location?
                if char in sent:
                    for alias, loc2 in self._loc_aliases().items():
                        if loc2 != loc and alias in sent:
                            if not any(w in self.body for w in MOVE_WORDS):
                                self.add("WARNING", "CHARACTER_LOCATION",
                                         f"{char} appears at {loc2} but canon notes {loc}",
                                         sent.strip()[:120],
                                         "novel/plot/current-arc.md",
                                         "補上移動／傳送交代，或由作者確認位置。")
                                hit = True
                            break
        self.record("C3D-003", "Character Location", "WARNING" if hit else "PASS")

    def _loc_aliases(self) -> dict[str, str]:
        out = {}
        for canon, als in cb.ENTITIES.get("location", {}).items():
            for a in als:
                out[a] = canon
        return out

    def check_ability(self) -> None:
        names, canon_of = roster()
        worst = "PASS"
        for sent in story_sentences(self.body):
            for ab, (owner, src) in EXCLUSIVE_ABILITY_OWNER.items():
                if ab not in sent:
                    continue
                for nm in names:
                    if len(nm) < 2 or nm == owner or nm == ab \
                            or canon_of.get(nm) == owner:
                        continue
                    if nm in sent and not any(w in sent for w in DEATH_CONTEXT + ["聽說", "傳聞"]):
                        self.add("ERROR", "ABILITY",
                                 f"Exclusive ability used by non-owner: {ab} by {nm} (owner: {owner})",
                                 sent.strip()[:120], src,
                                 "修正持有者或由作者確認；不得擅改能力規則。")
                        worst = "ERROR"
                        break
            for st in STAGE_WORDS:
                if st in sent and any(a in sent for a in ACTIVATE_WORDS):
                    self.add("ERROR", "ABILITY",
                             f"Unreleased stage treated as activated: {st}",
                             sent.strip()[:120],
                             "novel/canon/abilities.md, novel/plot/current-arc.md",
                             "神覺尚未於正文觸發；不得寫成已啟動，或標 [PROPOSED] 待確認。")
                    worst = "ERROR"
        self.record("C3D-004", "Ability", worst)

    def check_weapon(self) -> None:
        names, canon_of = roster()
        worst = "PASS"
        for sent in story_sentences(self.body):
            for wp, (owner, src) in EXCLUSIVE_WEAPON_OWNER.items():
                if wp not in sent:
                    continue
                for nm in names:
                    if len(nm) < 2 or nm == owner or nm == wp \
                            or canon_of.get(nm) == owner:
                        continue
                    if nm in sent and not any(w in sent for w in DEATH_CONTEXT):
                        sev = "WARNING" if owner == "奧法辛" else "ERROR"
                        self.add(sev, "WEAPON",
                                 f"Weapon holder mismatch: {wp} by {nm} (owner: {owner})",
                                 sent.strip()[:120], src,
                                 "修正持有者或由作者確認；未知新武器標 [NEW_SETTING]。")
                        if sev == "ERROR":
                            worst = "ERROR"
                        elif worst == "PASS":
                            worst = "WARNING"
                        break
        self.record("C3D-005", "Weapon", worst)

    def check_timeline(self) -> None:
        worst = "PASS"
        target = str((self.meta.get("target") or ""))
        tm = re.match(r"chapter-(\d+)", target)
        tnum = int(tm.group(1)) if tm else None
        for pat in CHAPTER_RES:
            for m in pat.finditer(self.body):
                try:
                    n = int(m.group(1))
                except ValueError:
                    continue
                if n > 59 and n != tnum:
                    self.add("ERROR", "TIMELINE",
                             f"References nonexistent Chapter #{n}",
                             m.group(0), "novel/chapters/",
                             "修正章節引用；續寫目標章除外。")
                    worst = "ERROR"
        # future plans stated as facts
        for sec in self._future_sections():
            keys = [k for k in keywords(sec) if len(k) >= 4]
            if any(k in self.body for k in keys) and "[PROPOSED]" not in self.body:
                self.add("WARNING", "TIMELINE",
                         f"Future plan stated as established fact: {sec[:24]}",
                         sec[:80], "novel/plot/future.md",
                         "未來規劃須保留 [PROPOSED] 標記，不得寫成已發生。")
                worst = "WARNING" if worst == "PASS" else worst
                break
        self.record("C3D-006", "Timeline", worst)

    def _future_sections(self) -> list[str]:
        secs = []
        cur = None
        for line in read_text(ROOT / "novel" / "plot" / "future.md").splitlines():
            m = re.match(r"^###\s+(.+?)\s*$", line)
            if m:
                if cur:
                    secs.append(cur)
                cur = m.group(1)
        if cur:
            secs.append(cur)
        return secs

    def check_continuity_059(self) -> None:
        target = str((self.meta.get("target") or ""))
        if not target.startswith("chapter-060"):
            self.record("C3D-007", "Continuity #059", "SKIP")
            return
        anchors = ["蛛皇", "真空", "邊境", "防線", "六星", "發散", "戰場"]
        if not any(a in self.body for a in anchors):
            self.add("WARNING", "CONTINUITY_059",
                     "CONTINUE draft shows no link to #059 ending state",
                     (self.body[:120].replace("\n", " ")),
                     "novel/chapters/059.md, novel/plot/current-arc.md",
                     "承接 #059 結尾（角色狀態／戰場／真空現場），或說明時間跳接。")
            self.record("C3D-007", "Continuity #059", "WARNING")
        else:
            self.record("C3D-007", "Continuity #059", "PASS")

    def check_conflict(self) -> None:
        worst = "PASS"
        for it in review_items("conflicts.md", "C"):
            blob = it["id"] + " " + it["title"] + " " + it["text"][:500]
            keys = keywords(blob)
            if mentioned(keys, it["id"], self.body):
                status = "[RESOLVED]" if "### 目前狀態\n[RESOLVED]" in it["text"] \
                    else "[UNRESOLVED]"
                if status == "[UNRESOLVED]":
                    extra = "（C-004 無生血界：不得選用任一版本）" if it["id"] == "C-004" else ""
                    self.add("WARNING", "CONFLICT",
                             f"Draft touches unresolved {it['id']}{extra}",
                             (it["title"] or it["id"])[:80],
                             "novel/review/conflicts.md",
                             "[NEEDS_AUTHOR_DECISION] No silent resolution.")
                    worst = "WARNING"
        self.record("C3D-008", "Conflict Safety", worst)

    def check_proposed(self) -> None:
        adopted = set(self.meta.get("proposed_used") or [])
        worst = "PASS"
        for it in review_items("proposed.md", "P"):
            if it["id"] in adopted:
                continue
            if mentioned(keywords(it["id"] + " " + it["title"]), it["id"], self.body) \
                    and "[PROPOSED]" not in self.body:
                self.add("WARNING", "PROPOSED_USAGE",
                         f"Draft uses unadopted proposed setting: {it['id']}",
                         (it["title"] or it["id"])[:80],
                         "novel/review/proposed.md",
                         "[NEEDS_AUTHOR_DECISION] 合理也不得自動變成 Canon。")
                worst = "WARNING"
        self.record("C3D-009", "Proposed Safety", worst)

    def check_inferred(self) -> None:
        worst = "PASS"
        for it in review_items("inferred.md", "I"):
            keys = [k for k in keywords(it["id"] + " " + it["title"]) if len(k) >= 4]
            hit = it["id"] in self.body or any(k in self.body for k in keys)
            if not hit:
                continue
            hedged = False
            for sent in story_sentences(self.body):
                if any(k in sent for k in keys) or it["id"] in sent:
                    if any(h in sent for h in HEDGE_WORDS):
                        hedged = True
                    else:
                        self.add("WARNING", "INFERRED_USAGE",
                                 "Draft promotes inferred information to explicit fact: "
                                 + it["id"],
                                 sent.strip()[:120],
                                 "novel/review/inferred.md",
                                 "改為推測語氣或標 [INFERRED]；禁止升級成 Canon。")
                        worst = "WARNING"
                    break
            if hit and hedged and worst == "PASS":
                pass
        self.record("C3D-010", "Inferred Safety", worst)

    def check_foreshadowing(self) -> None:
        worst = "PASS"
        for sec in self._numbered(ROOT / "novel" / "plot" / "foreshadowing.md"):
            if title_hit(sec, "", self.body):
                self.add("WARNING", "FORESHADOWING",
                         f"Draft may touch existing foreshadowing: {sec[:30]}",
                         sec[:80], "novel/plot/foreshadowing.md",
                         "作者確認是否提前揭露／否定伏筆（本檢查不斷言一定破壞）。")
                worst = "WARNING"
        self.record("C3D-011", "Foreshadowing", worst)

    def check_unresolved(self) -> None:
        n = 0
        for sec in self._numbered(ROOT / "novel" / "plot" / "unresolved.md"):
            if title_hit(sec, "", self.body):
                self.add("INFO", "UNRESOLVED",
                         f"Draft touches open plot thread: {sec[:30]}",
                         sec[:80], "novel/plot/unresolved.md",
                         "解伏筆無須禁止；若同時違反 Canon 另見其餘 issue。")
                n += 1
        self.record("C3D-012", "Unresolved Plot", "INFO" if n else "PASS")

    def _numbered(self, path: Path) -> list[str]:
        secs, cur = [], None
        for line in read_text(path).splitlines():
            m = re.match(r"^###\s+(.+?)\s*$", line)
            if m:
                if cur:
                    secs.append(cur)
                cur = m.group(1)
        if cur:
            secs.append(cur)
        return secs

    def check_ai_idea(self) -> None:
        worst = "PASS"
        for phrase in ai_idea_phrases():
            if phrase in self.body:
                self.add("WARNING", "AI_IDEA_USAGE",
                         "Draft uses an [AI IDEA] concept as if canon",
                         phrase[:80], "novel/ideas/",
                         "[AI IDEA] 不得視為 Canon；需作者確認。")
                worst = "WARNING"
                break
        self.record("C3D-013", "AI Idea Isolation", worst)

    # -- report ------------------------------------------------------------
    def run(self, before: dict) -> dict:
        if self.perr:
            self.add("ERROR", "DRAFT_PARSE", f"Draft frontmatter invalid: {self.perr}",
                     "", str(self.draft_path), "修正 draft frontmatter。")
            self.record("C3D-000", "Draft Parse", "ERROR")
        else:
            self.check_unknown_entity()
            self.check_character_status()
            self.check_character_location()
            self.check_ability()
            self.check_weapon()
            self.check_timeline()
            self.check_continuity_059()
            self.check_conflict()
            self.check_proposed()
            self.check_inferred()
            self.check_foreshadowing()
            self.check_unresolved()
            self.check_ai_idea()
        after = snapshot()
        modified = before != after
        details = sorted(set(after) ^ set(before))
        if modified:
            self.add("ERROR", "PROTECTED_FILE_MODIFIED",
                     "Checker run modified protected files",
                     ",".join(details[:5]), "PROTECTED_DIRS",
                     "調查並還原異動；測試必須失敗。")
        errors = sum(1 for i in self.issues if i["severity"] == "ERROR")
        warnings = sum(1 for i in self.issues if i["severity"] == "WARNING")
        infos = sum(1 for i in self.issues if i["severity"] == "INFO")
        status = "ERROR" if errors else ("WARNING" if warnings else "PASS")
        target = str((self.meta.get("target") or ""))
        tm = re.match(r"chapter-(\d+)", target)
        version = str((self.meta.get("draft_id") or ""))
        return {
            "schema_version": SCHEMA_VERSION,
            "draft": {"path": self.draft_path.relative_to(ROOT).as_posix()
                      if self.draft_path.is_absolute() else self.draft_path.as_posix(),
                      "chapter": tm.group(1) if tm else target,
                      "version": version},
            "canon_version": git_head(),
            "status": status,
            "summary": {"errors": errors, "warnings": warnings, "info": infos},
            "checks": self.checks,
            "issues": self.issues,
            "protected_files": {"modified": modified, "details": details[:10]},
        }


def to_markdown(rep: dict) -> str:
    L = ["# Consistency Report", "",
         f"Draft: {rep['draft']['path']}",
         f"Status: {rep['status']}", "", "## Summary", "",
         f"- Errors: {rep['summary']['errors']}",
         f"- Warnings: {rep['summary']['warnings']}",
         f"- Info: {rep['summary']['info']}", ""]
    for sev in ("ERROR", "WARNING", "INFO"):
        items = [i for i in rep["issues"] if i["severity"] == sev]
        if not items:
            continue
        L.append(f"## {sev.capitalize()}s" if sev != "INFO" else "## Info")
        L.append("")
        for it in items:
            L += [f"### {it['id']} — {it['category']}", "",
                  it["message"], "", "Evidence:", it["evidence"] or "(none)", "",
                  "Source:", it["source"] or "(none)", "", "Recommendation:",
                  it["recommendation"] or "(none)", ""]
    L += ["## Protected Files", "",
          ("PROTECTED FILES MODIFIED: " + ", ".join(rep["protected_files"]["details"])
           if rep["protected_files"]["modified"]
           else "No protected files modified."), ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Consistency / Quality Gate (read-only).")
    ap.add_argument("draft")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--output", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    before = snapshot()
    context = None
    if args.context:
        try:
            context = json.loads(Path(args.context).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"cannot load context: {exc}")
            return 2
    draft_path = Path(args.draft)
    if not draft_path.is_file():
        print(f"draft not found: {args.draft}")
        return 2
    rep = Checker(draft_path, context).run(before)
    # sanitize control chars for safe JSON output
    rep = json.loads(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "",
                            json.dumps(rep, ensure_ascii=False)))
    as_markdown = args.markdown and not args.json
    text = to_markdown(rep) if as_markdown else json.dumps(rep, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"report written: {args.output}")
    else:
        sys.stdout.write(text + "\n")
    errors = rep["summary"]["errors"]
    warnings = rep["summary"]["warnings"]
    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
