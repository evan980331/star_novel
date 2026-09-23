#!/usr/bin/env python3
"""Novel Editor Context Builder (phase 3B).

READ ONLY: retrieves Canon / Plot / Review context for a request and
emits a structured Writing Context as JSON or Markdown.

    python novel/editor/context_builder.py --request "續寫第60章"
    python novel/editor/context_builder.py --request "寫星星與沐寒戰鬥" --max-items 30
    python novel/editor/context_builder.py --request "分析星星目前能力" --format markdown

Never calls any LLM. Never modifies any file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CANON_DIR = ROOT / "novel" / "canon"
PLOT_DIR = ROOT / "novel" / "plot"
REVIEW_DIR = ROOT / "novel" / "review"
CHAPTERS_DIR = ROOT / "novel" / "chapters"

MAX_CHAPTER = 59
CHAPTER_EXCERPT_HEAD = 25
CHAPTER_EXCERPT_TAIL = 10
TEXT_TRUNCATE = 1200

CONFLICT_WARNING = (
    "WARNING:\nCanon conflict detected.\n"
    "Do not resolve automatically.\nAuthor decision required."
)

# ---------------------------------------------------------------------------
# Normalization & aliases
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(
    r"[\s\u3000，。、；：！？「」『』（）【】〈〉《》…—─·・"
    r".,;:!?()\[\]{}'\"`~@#$%^&*+=|\\/<>-]"
)


def norm(s: str) -> str:
    return _PUNCT_RE.sub("", s.lower())


# canonical name -> [aliases...] (aliases include the canonical name itself)
ENTITIES: dict[str, dict[str, list[str]]] = {
    "character": {
        "星星": ["星星", "主角", "星", "少女"],
        "沐寒": ["沐寒"],
        "希爾達": ["希爾達", "希尔达"],
        "索爾": ["索爾", "索尔", "光之子", "聖奧古斯汀", "圣奥古斯汀"],
        "百里": ["百里"],
        "修斯": ["修斯", "奧古斯特", "奥古斯特"],
        "雷昂": ["雷昂"],
        "巴羅": ["巴羅", "巴罗", "亞爾伯特", "亚尔伯特"],
        "雷恩": ["雷恩", "影尾"],
        "小橙": ["小橙"],
        "凱爾": ["凱爾", "凯尔", "銀袍", "银袍"],
        "副院長": ["副院長", "副院长"],
        "院長": ["院長", "院长"],
        "格蘭": ["格蘭", "格兰"],
        "深淵蛛皇": ["深淵蛛皇", "深渊蛛皇", "織命者", "织命者", "蛛皇"],
        "赫連震": ["赫連震", "赫连震", "震動人", "震动人"],
        "奧法辛": ["奧法辛", "奥法辛", "監察官", "监察官", "觀測之鏡", "观测之镜"],
        "碎牙": ["碎牙"],
        "零": ["零", "zero"],
        "蓮": ["蓮", "莲", "ren"],
        "祈": ["祈", "inori"],
        "蒼": ["蒼", "苍", "sou"],
        "濁": ["濁", "浊", "daku"],
        "水之神": ["水之神"],
    },
    "ability": {
        "神化": ["神化", "神化狀態"],
        "發散": ["發散", "发散", "開", "六星法皇"],
        "收斂": ["收斂", "收敛", "關"],
        "黑洞": ["黑洞", "黑洞屬性"],
        "神覺": ["神覺", "神觉", "絕對發散", "绝对发散", "絕對收斂", "绝对收敛", "奇點", "奇点"],
        "重力": ["重力", "引力", "重力操控", "引力彈弓", "重力彈弓", "重力絲線", "微操"],
        "變速": ["變速", "变速", "時差", "时差", "時差流星", "时差流星"],
        "領域": ["領域", "领域", "結界", "结界"],
        "神力": ["神力", "神力真空", "神力盾", "神力砲擊"],
    },
    "weapon": {
        "六星飛環": ["六星飛環", "六星飞环", "星環", "星环", "飛環", "飞环"],
        "星之劍": ["星之劍", "星之剑", "星劍"],
        "星之弓": ["星之弓", "星之弓"],
        "星之盾": ["星之盾", "星之盾"],
        "彗星手套": ["彗星手套", "流星手套", "手套"],
        "Stellar星斧": ["stellar", "星斧"],
        "鐵劍": ["鐵劍", "铁剑", "普通鐵劍"],
        "重劍": ["重劍", "重剑", "鎢鋼", "钨钢", "深海鎢鋼"],
    },
    "location": {
        "聖啟明皇家學院": ["聖啟明", "圣启明", "皇家學院", "皇家学院", "學院", "学院", "丁班", "丙班", "甲班", "乙班"],
        "帝都": ["帝都"],
        "荒原": ["荒原", "邊境", "边境", "防線", "防线", "亂石灘", "乱石滩"],
        "訓練場": ["訓練場", "训练场", "操場", "操场", "擂台", "訓練", "训练"],
        "觀星台": ["觀星台", "观星台", "後山", "后山"],
        "落日大峽谷": ["落日", "大峽谷", "大峡谷", "落日森林"],
        "巨獸森林": ["巨獸森林", "巨兽森林", "狩獵祭", "狩猎祭"],
        "荒古秘境": ["荒古", "秘境", "聖殿", "圣殿", "核心聖殿"],
        "雨之國": ["雨之國", "雨之国"],
        "遺落綠洲": ["綠洲", "绿洲", "遺落綠洲"],
        "黑市": ["黑市"],
        "監控大廳": ["監控", "监控"],
    },
    "faction": {
        "神裔家族": ["神裔", "神裔家族", "神裔長老", "赫連家", "赫连家"],
        "奧古斯特家族": ["奧古斯特", "奥古斯特", "奧古斯汀", "奥古斯汀"],
        "貴族": ["貴族", "贵族"],
        "監察官體系": ["監察", "监察"],
        "蠻荒": ["蠻荒", "蛮荒", "魔物", "深淵", "深渊", "祭司團"],
        "雨之國": ["雨之國", "雨之国"],
        "神棄者組織": ["神棄者", "神弃者"],
    },
}

# default relevant entities for CONTINUE requests (§8 續寫 Context 規則)
CONTINUE_DEFAULTS = [
    ("character", "星星"), ("character", "百里"), ("character", "希爾達"),
    ("character", "修斯"), ("character", "雷昂"), ("character", "深淵蛛皇"),
    ("ability", "黑洞"), ("ability", "收斂"), ("ability", "發散"),
    ("ability", "重力"), ("ability", "神力"),
    ("weapon", "六星飛環"), ("weapon", "星之劍"),
    ("location", "聖啟明皇家學院"), ("location", "荒原"),
    ("faction", "神裔家族"), ("faction", "蠻荒"),
]

# entity -> related entities (medium relevance boost)
RELATED: dict[str, list[str]] = {
    "星星": ["希爾達", "百里", "索爾", "沐寒", "修斯", "雷昂", "黑洞", "收斂", "發散"],
    "沐寒": ["星星", "神裔家族", "百里", "領域"],
    "索爾": ["星星", "神裔家族", "領域"],
    "希爾達": ["星星", "修斯", "百里"],
    "百里": ["星星", "小橙", "沐寒"],
    "修斯": ["希爾達", "雷昂", "奧古斯特家族"],
    "雷昂": ["修斯", "星星"],
    "深淵蛛皇": ["星星", "蠻荒", "荒原"],
    "赫連震": ["神裔家族", "星星", "碎牙"],
    "奧法辛": ["監察官體系", "星星", "深淵蛛皇"],
    "零": ["星星", "神棄者組織"],
    "蓮": ["雨之國", "百里", "星星"],
    "黑洞": ["星星", "神化", "收斂", "發散"],
    "神覺": ["黑洞", "神化", "Stellar星斧"],
    "重力": ["彗星手套", "星星", "變速"],
    "六星飛環": ["發散", "星星", "深淵蛛皇"],
    "星之劍": ["收斂", "星星", "星之弓", "星之盾"],
    "彗星手套": ["重力", "星星"],
    "聖啟明皇家學院": ["帝都", "貴族", "副院長", "凱爾"],
    "荒原": ["蠻荒", "深淵蛛皇", "聖啟明皇家學院"],
    "荒古秘境": ["沐寒", "星星", "百里"],
    "神裔家族": ["沐寒", "索爾", "赫連震", "奧古斯特家族"],
    "雨之國": ["蓮", "祈", "水之神", "濁", "蒼"],
}

CANON_FILE_FOR = {
    "character": "characters.md",
    "ability": "abilities.md",
    "weapon": "weapons.md",
    "location": "locations.md",
    "faction": "factions.md",
}
TERMINOLOGY_FILE = "terminology.md"
TIMELINE_FILE = "timeline.md"

# ---------------------------------------------------------------------------
# Task classification (multi-signal scoring, not single keyword)
# ---------------------------------------------------------------------------

TYPE_SIGNALS: dict[str, list[str]] = {
    "CONTINUE": ["續寫", "继续", "接著寫", "接续", "下一章", "下一集", "後續章節", "连载", "更新"],
    "BATTLE": ["戰鬥", "战斗", "對戰", "对战", "打鬥", "决斗", "決鬥", "交手", "開戰", "开战",
               "對決", "对决", "迎戰", "迎战", "單挑", "单挑", "宣戰"],
    "CHARACTER": ["人物", "角色", "人設", "性格", "關係", "关系", "背景故事", "小傳", "人際"],
    "ABILITY": ["能力", "技能", "招式", "屬性", "神化", "發散", "收斂", "黑洞", "神覺",
                "重力", "引力", "變速", "領域", "神力", "戰力", "實力"],
    "WORLD": ["世界", "世界觀", "國家", "體系", "制度", "設定集", "地理", "帝都", "雨之國"],
    "PLOT": ["劇情", "剧情", "情節", "伏筆", "大綱", "故事線", "未來", "時間線", "未解", "鋪陳",
             "發生", "发生", "經過", "经过"],
    "ANALYZE": ["分析", "解析", "整理", "總結", "盤點", "比較", "評估", "檢視"],
    "WRITE": ["寫", "創作", "起草", "描寫", "場景", "對話", "番外", "同人"],
}
# tie-break: more specific types first
TYPE_PRIORITY = ["CONTINUE", "BATTLE", "CHARACTER", "ABILITY", "WORLD", "PLOT", "ANALYZE", "WRITE", "UNKNOWN"]


def classify(request: str) -> str:
    nreq = norm(request)
    scores: dict[str, int] = {}
    for ttype, signals in TYPE_SIGNALS.items():
        scores[ttype] = sum(1 for s in signals if norm(s) in nreq)
    # chapter-continue pattern is a strong CONTINUE signal
    if re.search(r"續寫|继续|接著|接续|下一章|下一集", request):
        scores["CONTINUE"] += 3
    best = max(scores.values())
    if best == 0:
        # entity-only requests still map to a useful type
        detected, _ = detect_entities(request)
        cats = {c for c, _ in detected}
        if "character" in cats:
            return "CHARACTER"
        if "ability" in cats:
            return "ABILITY"
        return "UNKNOWN"
    winners = [t for t, s in scores.items() if s == best]
    for t in TYPE_PRIORITY:
        if t in winners:
            return t
    return "UNKNOWN"


CHAPTER_RES = [
    re.compile(r"第\s*(\d+)\s*章"),
    re.compile(r"#\s*(\d+)"),
    re.compile(r"chapter\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*集"),
]


def detect_chapters(request: str) -> tuple[list[int], int | None]:
    found: list[int] = []
    for pat in CHAPTER_RES:
        for m in pat.finditer(request):
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            if 0 <= n <= 99 and n not in found:
                found.append(n)
    continue_next: int | None = None
    if re.search(r"續寫|继续|接著|接续|下一章|下一集", request) and found:
        continue_next = max(found)
        found = [c for c in found if c != continue_next]
        if continue_next > 0 and (continue_next - 1) not in found:
            found.append(continue_next - 1)
    found = sorted({c for c in found if 0 <= c <= MAX_CHAPTER})
    return found, continue_next


def detect_entities(request: str) -> tuple[list[tuple[str, str]], str]:
    """Return ([(category, canonical)], normalized request)."""
    nreq = norm(request)
    found: list[tuple[str, str]] = []
    for cat, table in ENTITIES.items():
        for canon, aliases in table.items():
            if any(norm(a) in nreq for a in aliases):
                found.append((cat, canon))
    return found, nreq


# ---------------------------------------------------------------------------
# File parsing (read-only)
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(s: str) -> str:
    return _CONTROL_RE.sub("", s)


def parse_sections(path: Path) -> list[dict]:
    out: list[dict] = []
    cur = {"heading": "(top)", "lines": []}
    for line in read_text(path).splitlines():
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) == 2:
            if cur["lines"]:
                out.append({"heading": cur["heading"], "text": "\n".join(cur["lines"]).strip()})
            cur = {"heading": m.group(2).strip(), "lines": []}
        else:
            cur["lines"].append(line)
    if cur["lines"]:
        out.append({"heading": cur["heading"], "text": "\n".join(cur["lines"]).strip()})
    return [s for s in out if s["text"]]


def section_status(text: str) -> str:
    if "[CONFLICT]" in text:
        return "CONFLICT"
    if "[PROPOSED]" in text:
        return "PROPOSED"
    if "[INFERRED]" in text:
        return "INFERRED"
    return "CANON"


def truncate(text: str, limit: int = TEXT_TRUNCATE) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（截斷，原文更長）"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def score_section(nheading: str, ntext: str, aliases: list[str], related: list[str]) -> str | None:
    for a in aliases:
        if a and a in nheading:
            return "high"
    for a in aliases:
        if a and a in ntext:
            return "medium"
    for r in related:
        if r and (r in nheading or r in ntext):
            return "medium"
    return None


def retrieve_canon(detected: list[tuple[str, str]], nreq: str) -> dict[str, list[dict]]:
    canon: dict[str, list[dict]] = {k: [] for k in
        ["world", "characters", "abilities", "weapons", "factions",
         "locations", "relationships", "terminology"]}
    by_cat: dict[str, list[str]] = {}
    for cat, name in detected:
        by_cat.setdefault(cat, []).append(name)
    # locate each canon file's sections once
    for key, fname in [("world", "world.md"), ("characters", "characters.md"),
                       ("abilities", "abilities.md"), ("weapons", "weapons.md"),
                       ("factions", "factions.md"), ("locations", "locations.md"),
                       ("relationships", "relationships.md"),
                       ("terminology", "terminology.md")]:
        path = CANON_DIR / fname
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        for sec in parse_sections(path):
            if "[AI IDEA]" in sec["text"]:
                continue
            nheading, ntext = norm(sec["heading"]), norm(sec["text"])
            best: str | None = None
            for cat, names in by_cat.items():
                aliases: list[str] = []
                related: list[str] = []
                for name in names:
                    aliases.extend(norm(a) for a in ENTITIES.get(cat, {}).get(name, [name]))
                    related.extend(norm(r) for r in RELATED.get(name, []))
                r = score_section(nheading, ntext, aliases, related)
                if r == "high":
                    best = "high"
                    break
                if r == "medium":
                    best = "medium"
            if best is None:
                continue
            canon[key].append({
                "name": sec["heading"], "text": truncate(sec["text"]),
                "source": [rel], "relevance": best,
                "status": section_status(sec["heading"] + "\n" + sec["text"]),
            })
    return canon


def parse_numbered(path: Path, level: int = 3) -> list[dict]:
    items: list[dict] = []
    cur = None
    for line in read_text(path).splitlines():
        m = re.match(r"^(#{2,4})\s+(.+?)\s*$", line)
        if m and len(m.group(1)) == level:
            if cur and "".join(cur["lines"]).strip():
                items.append(cur)
            cur = {"name": m.group(2).strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur and cur["lines"]:
        items.append(cur)
    out = []
    for it in items:
        text = "\n".join(it["lines"]).strip()
        if text:
            out.append({"name": it["name"], "text": truncate(text)})
    return out


def retrieve_plot(detected_names: list[str], task_type: str,
                  chapters: list[int]) -> dict[str, list[dict]]:
    plot: dict[str, list[dict]] = {k: [] for k in
        ["current_arc", "timeline", "foreshadowing", "unresolved", "future", "chapters"]}
    aliases: list[str] = []
    for _cat, table in ENTITIES.items():
        for canon, als in table.items():
            if canon in detected_names:
                aliases.extend(norm(a) for a in als)

    def match(name: str, text: str) -> str | None:
        nname, ntext = norm(name), norm(text)
        for a in aliases:
            if a and (a in nname or a in ntext):
                return "high" if a in nname else "medium"
        return None

    # current-arc: CONTINUE → all high; else keyword match
    for it in parse_numbered(PLOT_DIR / "current-arc.md", 2) + parse_numbered(PLOT_DIR / "current-arc.md", 3):
        rel = (PLOT_DIR / "current-arc.md").relative_to(ROOT).as_posix()
        if task_type == "CONTINUE":
            plot["current_arc"].append({**it, "source": [rel], "relevance": "high"})
        elif (m := match(it["name"], it["text"])):
            plot["current_arc"].append({**it, "source": [rel], "relevance": m})

    # timeline: [#NNN] entries; CONTINUE → recent 5 high
    tlines = [l for l in read_text(PLOT_DIR / "timeline.md").splitlines() if l.startswith("[#")]
    trel = (PLOT_DIR / "timeline.md").relative_to(ROOT).as_posix()
    if task_type == "CONTINUE":
        for l in tlines[-5:]:
            m = re.match(r"\[#(\d+)\]\s*(.*)", l)
            plot["timeline"].append({"name": f"#{m.group(1)}" if m else "#?",
                                     "text": truncate(l), "source": [trel], "relevance": "high"})
    for l in tlines:
        m = re.match(r"\[#(\d+)\]\s*(.*)", l)
        num = int(m.group(1)) if m else -1
        hit = match(l, l) or (num in chapters)
        if hit:
            entry = {"name": f"#{num:03d}" if m else "#?",
                     "text": truncate(l), "source": [trel],
                     "relevance": "high" if num in chapters else hit}
            if all(e["name"] != entry["name"] for e in plot["timeline"]):
                plot["timeline"].append(entry)

    for key, fname in [("foreshadowing", "foreshadowing.md"),
                       ("unresolved", "unresolved.md"),
                       ("future", "future.md")]:
        for it in parse_numbered(PLOT_DIR / fname, 3):
            rel = (PLOT_DIR / fname).relative_to(ROOT).as_posix()
            if task_type == "CONTINUE" and key in ("foreshadowing", "unresolved", "future"):
                plot[key].append({**it, "source": [rel], "relevance": "high"})
            elif (m2 := match(it["name"], it["text"])):
                plot[key].append({**it, "source": [rel], "relevance": m2})

    # chapter excerpts (bounded, never full text)
    for num in chapters:
        p = CHAPTERS_DIR / f"{num:03d}.md"
        if not p.is_file():
            continue
        lines = read_text(p).splitlines()
        excerpt = lines[:CHAPTER_EXCERPT_HEAD] + ["…（中略，摘錄）…"] + lines[-CHAPTER_EXCERPT_TAIL:]
        plot["chapters"].append({
            "name": f"Chapter #{num:03d}（摘錄）",
            "text": truncate("\n".join(excerpt), TEXT_TRUNCATE),
            "source": [p.relative_to(ROOT).as_posix()],
            "relevance": "high", "excerpt": True,
        })
    return plot


def parse_review_items(fname: str, prefix: str) -> list[dict]:
    items: list[dict] = []
    cur = None
    for line in read_text(REVIEW_DIR / fname).splitlines():
        m = re.match(r"^#{2,3}\s+(" + re.escape(prefix) + r"(?:-[ABC])?-?\d+)\b\s*(.*)$", line.strip())
        if m:
            if cur and "".join(cur["lines"]).strip():
                items.append(cur)
            cur = {"id": m.group(1), "title": (m.group(2) or "").strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
    if cur and cur["lines"]:
        items.append(cur)
    out = []
    for it in items:
        title = it["title"]
        if not title:
            # conflicts.md uses "## C-001" + "### 類型" layout: fall back to 類型 line
            m2 = re.search(r"^###\s*類型\s*\n(.+?)\s*$", "\n".join(it["lines"]), re.M)
            if m2:
                title = m2.group(1).strip()
        out.append({"id": it["id"], "title": title or it["id"],
                    "text": "\n".join(it["lines"]).strip()})
    return out


def retrieve_review(detected_names: list[str], task_type: str) -> dict:
    aliases = []
    for _cat, table in ENTITIES.items():
        for canon, als in table.items():
            if canon in detected_names:
                aliases.extend(norm(a) for a in als)
    def hit(text: str) -> bool:
        ntext = norm(text)
        return any(a and a in ntext for a in aliases)

    review: dict = {"conflicts": [], "proposed": [], "inferred": [],
                    "author_decisions_pending": []}
    for it in parse_review_items("conflicts.md", "C"):
        status = "[RESOLVED]" if "### 目前狀態\n[RESOLVED]" in it["text"] else "[UNRESOLVED]"
        if task_type == "CONTINUE" or hit(it["id"] + it["title"] + it["text"]) or status == "[UNRESOLVED]":
            # unresolved conflicts always surface; resolved only on keyword hit
            if status == "[UNRESOLVED]" or hit(it["id"] + it["title"] + it["text"]):
                review["conflicts"].append({
                    "id": it["id"], "title": it["title"] or it["id"],
                    "status": status,
                    "sources": ["novel/review/conflicts.md"],
                    "excerpt": it["text"][:300],
                })
    for it in parse_review_items("proposed.md", "P"):
        text = it["id"] + it["title"] + it["text"]
        if task_type == "CONTINUE" or hit(text):
            if task_type == "CONTINUE" and not hit(text):
                continue
            rel = "high" if hit(it["id"] + it["title"]) else "medium"
            review["proposed"].append({
                "id": it["id"], "title": it["title"] or it["id"],
                "status": "PROPOSED",
                "confidence": "",
                "source": ["novel/review/proposed.md"],
                "reason": "未經作者確認的未來設定，不得當成正式 Canon。",
                "relevance": rel,
            })
    for it in parse_review_items("inferred.md", "I"):
        conf = "high" if it["id"].startswith("I-A") else ("medium" if it["id"].startswith("I-B") else "low")
        srcs = re.findall(r"Chapter #(\d+)", it["text"])
        text = it["id"] + it["title"] + it["text"]
        if task_type == "CONTINUE" or hit(text):
            if task_type == "CONTINUE" and conf == "low" and not hit(text):
                continue
            rel = "high" if hit(it["id"] + it["title"]) else "medium"
            review["inferred"].append({
                "id": it["id"], "title": it["title"] or it["id"],
                "status": "INFERRED", "confidence": conf,
                "source": [f"#{s}" for s in srcs] + ["novel/review/inferred.md"],
                "reason": "AI/分析根據正文推導，禁止自動升級成 Canon。",
                "relevance": rel,
            })
    # pending author decisions (rows in 待確認 table)
    in_pending = False
    for line in read_text(REVIEW_DIR / "author-decisions.md").splitlines():
        if line.strip().startswith("## "):
            in_pending = "待確認" in line
            continue
        if in_pending and line.strip().startswith("|") and "待確認" in line and not line.strip().startswith("| ID"):
            review["author_decisions_pending"].append(line.strip())
    return review


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def apply_max_items(ctx: dict, max_items: int) -> None:
    # (kind, list, index); review items outrank canon/plot at equal relevance
    pool: list[tuple[str, list, int]] = []
    for key, items in ctx["canon"].items():
        for i, _ in enumerate(items):
            pool.append(("canon", ctx["canon"][key], i))
    for key, items in ctx["plot"].items():
        for i, _ in enumerate(items):
            pool.append(("plot", ctx["plot"][key], i))
    for i, _ in enumerate(ctx["review"]["proposed"]):
        pool.append(("review", ctx["review"]["proposed"], i))
    for i, _ in enumerate(ctx["review"]["inferred"]):
        pool.append(("review", ctx["review"]["inferred"], i))
    if len(pool) <= max_items:
        return
    # keep all high first, then canon/plot medium (Canon priority),
    # then review medium, then low
    def rank(ref: tuple[str, list, int]) -> tuple[int, int, int]:
        kind, lst, i = ref
        rel = lst[i].get("relevance", "medium")
        order = {"high": 0, "medium": 1, "low": 2}
        o = order.get(rel, 1)
        group = 0 if o != 1 else (1 if kind != "review" else 2)
        if o == 2:
            group = 3
        return (o, group, i)
    pool_sorted = sorted(pool, key=rank)
    keep_refs = set()
    for _kind, lst, i in pool_sorted[:max_items]:
        keep_refs.add((id(lst), i))
    for key in list(ctx["canon"].keys()):
        ctx["canon"][key] = [it for i, it in enumerate(ctx["canon"][key])
                              if (id(ctx["canon"][key]), i) in keep_refs]
    for key in list(ctx["plot"].keys()):
        ctx["plot"][key] = [it for i, it in enumerate(ctx["plot"][key])
                             if (id(ctx["plot"][key]), i) in keep_refs]
    ctx["review"]["proposed"] = [it for i, it in enumerate(ctx["review"]["proposed"])
                                 if (id(ctx["review"]["proposed"]), i) in keep_refs]
    ctx["review"]["inferred"] = [it for i, it in enumerate(ctx["review"]["inferred"])
                                 if (id(ctx["review"]["inferred"]), i) in keep_refs]
    ctx["warnings"].append(
        f"Context truncated by --max-items={max_items}; conflicts and pending "
        f"author decisions are always kept."
    )


def build_context(request: str, max_items: int = 40) -> dict:
    task_type = classify(request)
    detected, _nreq = detect_entities(request)
    if task_type == "CONTINUE":
        for d in CONTINUE_DEFAULTS:
            if d not in detected:
                detected.append(d)
    # one-hop related expansion: related entities join as secondary signals
    primary = [name for _, name in detected]
    for name in list(primary):
        for rel in RELATED.get(name, []):
            for cat, table in ENTITIES.items():
                if rel in table and (cat, rel) not in detected:
                    detected.append((cat, rel))
    detected_names = [name for _, name in detected]
    chapters, continue_next = detect_chapters(request)

    canon = retrieve_canon(detected, norm(request))
    plot = retrieve_plot(detected_names, task_type, chapters)
    review = retrieve_review(detected_names, task_type)

    # story state
    notes: list[str] = []
    last_ch = None
    if plot["chapters"]:
        last = plot["chapters"][-1]
        last_ch = {"name": last["name"], "excerpt": True, "source": last["source"]}
        notes.append(f"已讀取章節摘錄：{last['name']}（非全文）。")
    if continue_next is not None:
        notes.append(f"續寫目標：第{continue_next}章；已讀取前章摘錄與 current-arc / timeline / foreshadowing / unresolved / future。")
    if task_type == "CONTINUE" and not chapters and continue_next is None:
        p = CHAPTERS_DIR / f"{MAX_CHAPTER:03d}.md"
        lines = read_text(p).splitlines()
        excerpt = lines[:CHAPTER_EXCERPT_HEAD] + ["…（中略，摘錄）…"] + lines[-CHAPTER_EXCERPT_TAIL:]
        plot["chapters"].append({
            "name": f"Chapter #{MAX_CHAPTER:03d}（摘錄）",
            "text": truncate("\n".join(excerpt), TEXT_TRUNCATE),
            "source": [p.relative_to(ROOT).as_posix()],
            "relevance": "high", "excerpt": True,
        })
        last_ch = {"name": f"Chapter #{MAX_CHAPTER:03d}（摘錄）",
                   "excerpt": True, "source": [p.relative_to(ROOT).as_posix()]}
        notes.append(f"未指定章節，預設讀取最新章 #{MAX_CHAPTER} 摘錄。")

    ctx: dict = {
        "request": request,
        "task_type": task_type,
        "detected": {"entities": detected_names, "chapters": chapters,
                     "continue_next": continue_next},
        "story_state": {
            "summary": f"{task_type} request：{request}",
            "last_chapter": last_ch,
            "notes": notes,
        },
        "canon": canon,
        "plot": plot,
        "review": review,
        "source_trace": [],
        "warnings": [],
    }

    # source trace
    for key, items in canon.items():
        for it in items:
            ctx["source_trace"].append(
                {"type": key.rstrip("s") if key != "abilities" else "ability",
                 "name": it["name"], "source": it["source"]})
    for key, items in plot.items():
        for it in items:
            ctx["source_trace"].append(
                {"type": f"plot:{key}", "name": it["name"], "source": it["source"]})

    # safety warnings
    if review["conflicts"]:
        ctx["warnings"].append(CONFLICT_WARNING)
        for c in review["conflicts"]:
            if c["status"] == "[UNRESOLVED]":
                ctx["warnings"].append(
                    f"{c['id']} [UNRESOLVED]: {c['title']} — "
                    f"Do not choose either version automatically."
                )
    if review["proposed"]:
        ctx["warnings"].append(
            f"{len(review['proposed'])} proposed item(s) included with [PROPOSED] "
            f"markers; do not present them as established facts."
        )
    if review["inferred"]:
        ctx["warnings"].append(
            f"{len(review['inferred'])} inferred item(s) included with confidence/source; "
            f"do not upgrade to Canon."
        )
    ctx["warnings"].append("[AI IDEA] excluded from Canon context.")

    apply_max_items(ctx, max_items)
    return ctx


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def to_markdown(ctx: dict) -> str:
    L: list[str] = ["# Novel Editor Context", "", "## Request", "",
                    ctx["request"], "", f"Task type: `{ctx['task_type']}`", ""]
    L += ["## Story State", "", ctx["story_state"]["summary"]]
    for n in ctx["story_state"]["notes"]:
        L.append(f"- {n}")
    L.append("")
    L += ["## Canon", ""]
    for key, items in ctx["canon"].items():
        L.append(f"### {key.capitalize()}")
        if not items:
            L.append("- （無相關條目）")
        for it in items:
            tag = f"[{it['status']}]" if it["status"] != "CANON" else ""
            L.append(f"- **{it['name']}** {tag} ({it['relevance']})")
            L.append(f"  {it['text'].splitlines()[0][:200]}")
            L.append(f"  Source: {', '.join(it['source'])}")
        L.append("")
    L += ["## Plot", ""]
    for key, items in ctx["plot"].items():
        L.append(f"### {key}")
        if not items:
            L.append("- （無相關條目）")
        for it in items:
            L.append(f"- **{it['name']}** ({it['relevance']})")
            first = it["text"].splitlines()[0][:200] if it["text"] else ""
            L.append(f"  {first}")
            L.append(f"  Source: {', '.join(it['source'])}")
        L.append("")
    L += ["## Review", ""]
    L.append("### Conflicts")
    for c in ctx["review"]["conflicts"]:
        L.append(f"- **{c['id']}** {c['status']}: {c['title']}")
    L.append("")
    L.append("### Proposed")
    for p in ctx["review"]["proposed"]:
        L.append(f"- [{p['id']}] {p['title']} — status: PROPOSED")
    L.append("")
    L.append("### Inferred")
    for f in ctx["review"]["inferred"]:
        L.append(f"- [{f['id']}] {f['title']} — status: INFERRED, confidence: {f['confidence']}")
    L.append("")
    L.append("### Pending author decisions")
    for row in ctx["review"]["author_decisions_pending"]:
        L.append(f"- {row}")
    L += ["", "## Warnings", ""]
    for w in ctx["warnings"]:
        L.append(f"- {w}")
    L += ["", "## Source Trace", ""]
    for s in ctx["source_trace"]:
        L.append(f"- [{s['type']}] {s['name']} ← {', '.join(s['source'])}")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Novel Editor Context Builder (read-only).")
    ap.add_argument("--request", required=True, help="user request, e.g. 續寫第60章")
    ap.add_argument("--format", choices=["json", "markdown"], default="json")
    ap.add_argument("--max-items", type=int, default=40)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ctx = build_context(args.request, max_items=args.max_items)
    ctx = json.loads(clean(json.dumps(ctx, ensure_ascii=False)))
    if args.format == "markdown":
        sys.stdout.write(to_markdown(ctx))
    else:
        json.dump(ctx, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
