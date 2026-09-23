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
REVIEW_DIR = ROOT / "novel" / "review"

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


REVIEW_FILES = [
    "README.md",
    "conflicts.md",
    "proposed.md",
    "inferred.md",
    "author-decisions.md",
    "review-status.json",
]

# README files contain tag *definitions/examples*, not real entries.
REVIEW_EXCLUDED_DOCS = {"novel/canon/README.md"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _tag_occurrences(tag: str) -> list[tuple[str, int, str]]:
    """All (rel, lineno, line) occurrences of tag across the 18 files."""
    out: list[tuple[str, int, str]] = []
    for base, name in ALL_18_FILES:
        path = base / name
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
            if tag in line:
                out.append((rel, lineno, line))
    return out


def _real_occurrences(tag: str) -> list[tuple[str, int, str]]:
    """Occurrences excluding documentation/README examples and
    blockquote instruction lines (lines starting with '>')."""
    out: list[tuple[str, int, str]] = []
    for rel, lineno, line in _tag_occurrences(tag):
        if rel in REVIEW_EXCLUDED_DOCS:
            continue
        if line.strip().startswith(">"):
            continue
        out.append((rel, lineno, line))
    return out


def _review_ids(filename: str, prefix: str) -> list[str]:
    path = REVIEW_DIR / filename
    if not path.is_file():
        return []
    pat = re.compile(r"^#{2,3}\s+(" + re.escape(prefix) + r"-?\d+)\b")
    ids: list[str] = []
    for line in _read_text(path).splitlines():
        m = pat.match(line.strip())
        if m:
            ids.append(m.group(1))
    return ids


def run_review() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print("===== Review 目錄完整性 =====")
    for name in REVIEW_FILES:
        if (REVIEW_DIR / name).is_file():
            print(f"  - [OK] novel/review/{name}")
        else:
            errors.append(f"review 缺檔：novel/review/{name}")
            print(f"  - [MISSING] novel/review/{name}")
    print()

    conflict_occs = _real_occurrences("[CONFLICT]")
    proposed_occs = _real_occurrences("[PROPOSED]")
    inferred_occs = _real_occurrences("[INFERRED]")
    print("===== 實際標記掃描（排除 canon/README 範例） =====")
    print(f"[CONFLICT]: {len(conflict_occs)} 次")
    print(f"[PROPOSED]: {len(proposed_occs)} 次")
    print(f"[INFERRED]: {len(inferred_occs)} 次")
    print()

    conflicts_text = _read_text(REVIEW_DIR / "conflicts.md")
    proposed_text = _read_text(REVIEW_DIR / "proposed.md")
    inferred_text = _read_text(REVIEW_DIR / "inferred.md")
    decisions_text = _read_text(REVIEW_DIR / "author-decisions.md")

    # 1. 所有 [CONFLICT] 是否都有對應 review 項目
    print("===== [1] CONFLICT 追蹤覆蓋 =====")
    conflict_files = sorted({o[0] for o in conflict_occs})
    for rel in conflict_files:
        basename = Path(rel).name
        if basename in conflicts_text or rel in conflicts_text:
            print(f"  - [OK] {rel} 已被 conflicts.md 引用")
        else:
            errors.append(f"[CONFLICT] 未追蹤：{rel}")
            print(f"  - [MISS] {rel} 未被 conflicts.md 引用")
    if not conflict_files:
        warnings.append("全庫無實際 [CONFLICT]（含 README 範例除外）")
    print()

    # 2. 所有 [PROPOSED] 是否都有追蹤
    print("===== [2] PROPOSED 追蹤覆蓋 =====")
    for rel in sorted({o[0] for o in proposed_occs}):
        basename = Path(rel).name
        if basename in proposed_text or rel in proposed_text:
            print(f"  - [OK] {rel} 已被 proposed.md 引用")
        else:
            errors.append(f"[PROPOSED] 未追蹤：{rel}")
            print(f"  - [MISS] {rel} 未被 proposed.md 引用")
    print()

    # 3. 所有 [INFERRED] 是否都有來源
    print("===== [3] INFERRED 來源檢查 =====")
    for rel in sorted({o[0] for o in inferred_occs}):
        basename = Path(rel).name
        if basename in inferred_text or rel in inferred_text:
            print(f"  - [OK] {rel} 已被 inferred.md 引用")
        else:
            errors.append(f"[INFERRED] 未追蹤：{rel}")
            print(f"  - [MISS] {rel} 未被 inferred.md 引用")
    # INFERRED 缺 Source 註記：同檔 6 行內無 Source 即告警
    for rel, lineno, line in inferred_occs:
        path = ROOT / rel
        lines = _read_text(path).splitlines()
        window = "\n".join(lines[max(0, lineno - 4):lineno + 6])
        if "Source" not in window and "來源" not in window:
            warnings.append(f"[INFERRED] 可能缺來源：{rel}:{lineno}")
    print()

    # 4. 是否有 Canon 檔案直接把 [PROPOSED] 當成正式 Canon
    print("===== [4] PROPOSED 不得直寫為 Canon =====")
    for rel, lineno, line in proposed_occs:
        if not rel.startswith("novel/canon/"):
            continue
        path = ROOT / rel
        lines = _read_text(path).splitlines()
        # 標題行本身帶 [PROPOSED] 時，來源常在下方子段落：向後看 15 行
        window = "\n".join(lines[max(0, lineno - 7):lineno + 15])
        if "Source" not in window and "來源" not in window:
            errors.append(f"Canon 內 [PROPOSED] 缺來源標註：{rel}:{lineno}")
            print(f"  - [FAIL] {rel}:{lineno}")
    # 已知結構問題（無生血界標記矛盾）必須被 conflicts 追蹤
    if "無生血界" in _read_text(CANON_DIR / "terminology.md"):
        if "C-004" in conflicts_text:
            print("  - [OK] 無生血界標記矛盾已由 C-004 追蹤")
        else:
            errors.append("無生血界標記矛盾未被 conflicts 追蹤")
            print("  - [FAIL] 無生血界標記矛盾未被追蹤")
    print("  檢查完成。")
    print()

    # 5. 是否有 [AI IDEA] 滲入 Canon
    print("===== [5] AI IDEA 不得進入 Canon =====")
    ai_canon = [o for o in _tag_occurrences("[AI IDEA]") if o[0].startswith("novel/canon/")]
    ai_canon_real = [o for o in ai_canon if o[0] not in REVIEW_EXCLUDED_DOCS]
    if ai_canon_real:
        for rel, lineno, _line in ai_canon_real:
            errors.append(f"[AI IDEA] 滲入 Canon：{rel}:{lineno}")
            print(f"  - [FAIL] {rel}:{lineno}")
    else:
        print("  - [OK] Canon 無 [AI IDEA]（canon/README 範例除外）")
    print()

    # 6. review-status.json 統計是否正確
    print("===== [6] review-status.json 統計 =====")
    c_ids = _review_ids("conflicts.md", "C")
    p_ids = _review_ids("proposed.md", "P")
    i_a = _review_ids("inferred.md", "I-A")
    i_b = _review_ids("inferred.md", "I-B")
    i_c = _review_ids("inferred.md", "I-C")
    try:
        import json as _json

        status = _json.loads(_read_text(REVIEW_DIR / "review-status.json"))
        checks = [
            (status["conflicts"]["total"], len(c_ids), "conflicts.total"),
            (status["conflicts"]["unresolved"], conflicts_text.count("[UNRESOLVED]"), "conflicts.unresolved"),
            (status["proposed"]["total"], len(p_ids), "proposed.total"),
            (status["proposed"]["pending"], len(p_ids), "proposed.pending"),
            (status["inferred"]["total"], len(i_a) + len(i_b) + len(i_c), "inferred.total"),
            (status["inferred"]["high"], len(i_a), "inferred.high"),
            (status["inferred"]["medium"], len(i_b), "inferred.medium"),
            (status["inferred"]["low"], len(i_c), "inferred.low"),
        ]
        for actual, expected, key in checks:
            if actual != expected:
                errors.append(f"review-status.json {key}={actual}，實際={expected}")
                print(f"  - [FAIL] {key}: json={actual} 實際={expected}")
            else:
                print(f"  - [OK] {key}={actual}")
        # 待確認數 = 作者決策表待確認列數
        pending_rows = [
            ln for ln in decisions_text.splitlines()
            if ln.strip().startswith("|") and "待確認" in ln and ln.count("|") >= 5
            and not ln.strip().startswith("| ID")
        ]
        if status.get("author_decisions_pending") != len(pending_rows):
            errors.append(
                f"review-status.json author_decisions_pending={status.get('author_decisions_pending')}，實際={len(pending_rows)}"
            )
            print(f"  - [FAIL] author_decisions_pending: json={status.get('author_decisions_pending')} 實際={len(pending_rows)}")
        else:
            print(f"  - [OK] author_decisions_pending={len(pending_rows)}")
    except Exception as exc:
        errors.append(f"review-status.json 無法解析：{exc}")
        print(f"  - [FAIL] 無法解析 review-status.json：{exc}")
    print()

    # 7. author-decisions.md 是否包含所有待確認 Conflict
    print("===== [7] 作者決策表覆蓋 =====")
    for cid in c_ids:
        if cid in decisions_text:
            print(f"  - [OK] {cid} 已列入 author-decisions.md")
        else:
            errors.append(f"author-decisions 缺 {cid}")
            print(f"  - [MISS] {cid} 未列入 author-decisions.md")
    print()

    # 8. Chapter # 引用是否仍然有效
    print("===== [8] Chapter # 引用驗證 =====")
    invalid_refs = scan_chapter_refs()
    review_invalid: list[tuple[str, int, str]] = []
    for name in ["conflicts.md", "proposed.md", "inferred.md", "author-decisions.md", "README.md"]:
        path = REVIEW_DIR / name
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
            for m in CHAPTER_REF_RE.finditer(line):
                num = int(m.group(1))
                if num < 0 or num > 59:
                    review_invalid.append((rel, lineno, m.group(0)))
    all_invalid = invalid_refs + review_invalid
    if all_invalid:
        for rel, lineno, raw in all_invalid:
            errors.append(f"無效 Chapter 引用：{rel}:{lineno} -> {raw}")
            print(f"  - [FAIL] {rel}:{lineno} -> {raw}")
    else:
        print("  - [OK] 所有 Chapter # 引用皆有效（含 review/）")
    print()

    if warnings:
        print("警告：")
        for w in warnings:
            print(f"  - [WARN] {w}")
        print()
    if errors:
        print(f"review 檢查失敗：{len(errors)} 個錯誤。")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("review 檢查通過，未修改任何檔案。")
    return 0


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
    if "--review" in sys.argv:
        sys.exit(run_review())
    sys.exit(main())
