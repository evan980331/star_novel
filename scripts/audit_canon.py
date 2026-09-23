#!/usr/bin/env python3
"""Audit canon database: chapter presence, file inventory, tag counts, chapter reference validation, and summary stats (read-only)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS_DIR = ROOT / "novel" / "chapters"
CANON_DIR = ROOT / "novel" / "canon"
PLOT_DIR = ROOT / "novel" / "plot"
IDEAS_DIR = ROOT / "novel" / "ideas"

CANON_FILES = [
    "README.md",
    "world.md",
    "characters.md",
    "abilities.md",
    "weapons.md",
    "factions.md",
    "locations.md",
    "timeline.md",
    "relationships.md",
    "terminology.md",
]
PLOT_FILES = [
    "current-arc.md",
    "future.md",
    "foreshadowing.md",
    "unresolved.md",
]
IDEAS_FILES = [
    "ideas.md",
    "scenes.md",
    "battles.md",
    "discarded.md",
]

ALL_18_FILES = [
    *[(CANON_DIR, name) for name in CANON_FILES],
    *[(PLOT_DIR, name) for name in PLOT_FILES],
    *[(IDEAS_DIR, name) for name in IDEAS_FILES],
]

TAGS = [
    "[CONFLICT]",
    "[INFERRED]",
    "[PROPOSED]",
    "[AI IDEA]",
]

CHAPTER_REF_RE = re.compile(r"Chapter #(\d{1,3})")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+")

EXCLUDED_CHARACTER_SECTIONS = {"未登場角色", "已死亡角色", "參考名單", "其他"}


def check_chapters() -> tuple[int, list[str]]:
    found = 0
    missing: list[str] = []
    for i in range(60):
        name = f"{i:03d}.md"
        path = CHAPTERS_DIR / name
        if path.is_file():
            found += 1
        else:
            missing.append(name)
    return found, missing


def check_18_files() -> tuple[int, list[tuple[str, str]], list[tuple[str, str]]]:
    total = len(ALL_18_FILES)
    found_files: list[tuple[str, str]] = []
    missing_files: list[tuple[str, str]] = []
    for base, name in ALL_18_FILES:
        rel = (base / name).relative_to(ROOT).as_posix()
        if (base / name).is_file():
            found_files.append((rel, name))
        else:
            missing_files.append((rel, name))
    return total - len(missing_files), found_files, missing_files


def scan_tags() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for tag in TAGS:
        result[tag] = {"count": 0, "files": []}
    for base, name in ALL_18_FILES:
        path = base / name
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for tag in TAGS:
            c = text.count(tag)
            if c > 0:
                result[tag]["count"] += c
                result[tag]["files"].append((rel, c))
    return result


def scan_chapter_refs() -> list[tuple[str, int, str]]:
    invalid: list[tuple[str, int, str]] = []
    for base, name in ALL_18_FILES:
        path = base / name
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, start=1):
            for m in CHAPTER_REF_RE.finditer(line):
                raw = m.group(0)
                num = int(m.group(1))
                if num < 0 or num > 59:
                    invalid.append((rel, lineno, raw))
    return invalid


def _count_headings_skip_sections(path: Path, skip_sections: set[str] | None = None) -> int:
    if not path.is_file():
        return 0
    count = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 0
    for line in lines:
        m = HEADING_RE.match(line)
        if not m:
            continue
        title = m.group(2).strip()
        if skip_sections and title in skip_sections:
            continue
        count += 1
    return count


def _count_list_items_or_headings(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 0
    for line in lines:
        if HEADING_RE.match(line):
            count += 1
        elif LIST_ITEM_RE.match(line):
            count += 1
    return count


def summary_stats() -> dict[str, int]:
    return {
        "characters": _count_headings_skip_sections(
            CANON_DIR / "characters.md", EXCLUDED_CHARACTER_SECTIONS
        ),
        "abilities": _count_headings_skip_sections(CANON_DIR / "abilities.md"),
        "weapons": _count_headings_skip_sections(CANON_DIR / "weapons.md"),
        "locations": _count_headings_skip_sections(CANON_DIR / "locations.md"),
        "foreshadowing": _count_list_items_or_headings(PLOT_DIR / "foreshadowing.md"),
        "unresolved": _count_list_items_or_headings(PLOT_DIR / "unresolved.md"),
    }


def main() -> int:
    chapter_found, chapter_missing = check_chapters()
    print("===== 章節完整性檢查 (000.md ~ 059.md) =====")
    print(f"{chapter_found}/60 chapters")
    if chapter_missing:
        print("缺漏章節：")
        for m in chapter_missing:
            print(f"  - {m}")
    else:
        print("60 章完整，無缺漏。")
    print()

    file_found, found_list, missing_list = check_18_files()
    print("===== Canon / Plot / Ideas 18 檔存在性檢查 =====")
    print(f"{file_found}/18 files 存在")
    if missing_list:
        print("尚未建立之檔案：")
        for rel, _ in missing_list:
            print(f"  - [MISSING] {rel}")
    if found_list:
        print("已存在之檔案：")
        for rel, _ in found_list:
            print(f"  - [OK] {rel}")
    print()

    tag_result = scan_tags()
    print("===== 標記計數 =====")
    for tag in TAGS:
        data = tag_result[tag]
        print(f"{tag}: {data['count']} 筆")
        for rel, c in data["files"]:
            print(f"  - {rel}: {c} 筆")
    print()

    invalid_refs = scan_chapter_refs()
    print("===== Chapter # 引用驗證 (章節數字需在 0..59) =====")
    if invalid_refs:
        print(f"發現 {len(invalid_refs)} 個無效引用：")
        for rel, lineno, raw in invalid_refs:
            print(f"  - {rel}:{lineno} -> {raw}")
    else:
        print("所有 Chapter # 引用皆有效（或檔案尚無引用）。")
    print()

    stats = summary_stats()
    print("===== Summary 統計 =====")
    print(f"人物數 (characters.md H2/H3，排除區段標題)：{stats['characters']}")
    print(f"能力數 (abilities.md H2/H3)：{stats['abilities']}")
    print(f"武器數 (weapons.md H2/H3)：{stats['weapons']}")
    print(f"地點數 (locations.md H2/H3)：{stats['locations']}")
    print(f"伏筆數 (foreshadowing.md H2/H3 或項目清單)：{stats['foreshadowing']}")
    print(f"未解決數 (unresolved.md H2/H3 或項目清單)：{stats['unresolved']}")
    print()

    print("audit_canon.py 執行完成，未修改任何檔案。")
    return 0 if not chapter_missing else 1


if __name__ == "__main__":
    sys.exit(main())
