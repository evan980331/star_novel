#!/usr/bin/env python3
"""Parse Penana PDF → page TXT → chapter markdown files."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL_DIR = ROOT / "novel" / "source" / "penana" / "downloads"
PDF_PATH = DL_DIR / "penana-latest.pdf"
TXT_PATH = DL_DIR / "penana-latest.txt"
CHAPTERS_DIR = ROOT / "novel" / "chapters"
MANIFEST_PATH = ROOT / "novel" / "source" / "penana" / "manifest.json"
STORY_META = ROOT / "novel" / "source" / "penana" / "config.json"

# Match "#0", "#12", optional title after NBSP/space.
HASH_HEAD = re.compile(r"(?m)^#(\d+)\b[^\n]*")
# Match "第1集", "第 1 集", "第一集" style headings (standalone line or after #n already handled).
CJK_NUM = "零一二三四五六七八九十百"
EP_HEAD = re.compile(
    r"(?m)^第\s*(\d+)\s*[集篇章話]\b|^第([" + CJK_NUM + r"]+)\s*[集篇章話]"
)
CHAPTER_FILE = re.compile(r"^(\d{3})\.md$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cjk_digit(ch: str) -> int:
    return CJK_NUM.index(ch)


def parse_cjk_num(s: str) -> int | None:
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    total = 0
    if "百" in s:
        a, _, s = s.partition("百")
        total += (parse_cjk_num(a) or 1) * 100
    if "十" in s:
        a, _, b = s.partition("十")
        total += (1 if a == "" else parse_cjk_num(a) or 0) * 10
        total += parse_cjk_num(b) or 0
    elif s:
        total += parse_cjk_num(s) or 0
    return total


def scan_chapter_range(chapters_dir: Path | None = None) -> tuple[int, int, int] | None:
    """Return (start, end, count) from NNN.md files, or None if none exist."""
    d = chapters_dir or CHAPTERS_DIR
    if not d.is_dir():
        return None
    nums: list[int] = []
    for p in d.iterdir():
        if p.is_file():
            m = CHAPTER_FILE.match(p.name)
            if m:
                nums.append(int(m.group(1)))
    if not nums:
        return None
    return min(nums), max(nums), len(nums)


def load_config() -> dict:
    if STORY_META.is_file():
        return json.loads(STORY_META.read_text(encoding="utf-8"))
    return {}


def pdf_to_text(pdf_path: Path) -> tuple[str, dict]:
    import pymupdf

    if not pdf_path.is_file():
        raise FileNotFoundError(f"missing PDF: {pdf_path}")
    doc = pymupdf.open(str(pdf_path))
    parts: list[str] = []
    for i, page in enumerate(doc, start=1):
        parts.append(f"===== PAGE {i} =====\n{page.get_text()}")
    text = "\n".join(parts)
    meta = {"page_count": doc.page_count, "text_length": len(text)}
    doc.close()
    return text, meta


def find_body_start(text: str) -> int:
    """Skip table-of-contents block: first '#0' after TOC is body.

    Heuristic: body starts at the *second* occurrence of a line that is
    exactly '#0' (first is TOC), or first '#0' if only one.
    """
    matches = list(re.finditer(r"(?m)^#0\s*$", text))
    if len(matches) >= 2:
        return matches[1].start()
    if matches:
        return matches[0].start()
    # fallback: first chapter-like line
    m = re.search(r"(?m)^#\d+\b", text)
    return m.start() if m else 0


def split_chapters(text: str) -> list[tuple[int, str, str]]:
    """Return list of (chapter_number, heading_line, body_text)."""
    body = text[find_body_start(text):]
    positions: list[tuple[int, int, str]] = []  # abs_index, num, line

    for m in HASH_HEAD.finditer(body):
        num = int(m.group(1))
        line = body[m.start(): body.find("\n", m.start()) if body.find("\n", m.start()) != -1 else len(body)]
        positions.append((m.start(), num, line.strip()))

    if not positions:
        # try EP_HEAD lines
        for m in EP_HEAD.finditer(body):
            raw = m.group(1) or m.group(2)
            num = parse_cjk_num(raw)
            if num is None:
                continue
            line_end = body.find("\n", m.start())
            line = body[m.start(): line_end if line_end != -1 else len(body)]
            positions.append((m.start(), num, line.strip()))

    if not positions:
        print("No chapter markers detected; keeping full TXT only.")
        return []

    # Deduplicate same chapter numbers: keep the run in the body (later positions
    # for TOC-style duplicates are none after find_body_start; still dedupe).
    seen: set[int] = set()
    unique: list[tuple[int, int, str]] = []
    for pos, num, line in positions:
        if num in seen:
            continue
        seen.add(num)
        unique.append((pos, num, line))
    unique.sort(key=lambda x: x[0])

    chapters: list[tuple[int, str, str]] = []
    for i, (pos, num, line) in enumerate(unique):
        end = unique[i + 1][0] if i + 1 < len(unique) else len(body)
        chunk = body[pos:end]
        chapters.append((num, line, chunk.rstrip() + "\n"))
    return chapters


def write_chapters(chapters: list[tuple[int, str, str]]) -> None:
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    # clear previous generated chapter files only (000.md pattern)
    for old in CHAPTERS_DIR.glob("[0-9][0-9][0-9].md"):
        old.unlink()
    for num, _line, chunk in chapters:
        out = CHAPTERS_DIR / f"{num:03d}.md"
        out.write_text(chunk, encoding="utf-8")


def load_manifest() -> dict:
    if MANIFEST_PATH.is_file():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def save_manifest(man: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")


def build_manifest(
    *,
    pdf_hash: str,
    file_size: int,
    page_count: int,
    text_length: int,
    chapter_count: int,
    start: int,
    end: int,
    cfg: dict,
    parser_result: str = "ok",
    pdf_removed: bool = False,
) -> dict:
    requested_start = cfg.get("requested_start", start)
    requested_end = cfg.get("requested_end", end)
    status = (
        "complete"
        if parser_result == "ok"
        and chapter_count > 0
        and start <= requested_start
        and end >= requested_end
        else "incomplete"
    )
    return {
        "story_id": str(cfg.get("story_id", "216000")),
        "source": cfg.get("source", "penana"),
        "source_url": cfg.get("story_url", ""),
        "download_url": cfg.get("pdf_url", ""),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "downloaded_start": start,
        "downloaded_end": end,
        "downloaded_chapter_count": chapter_count,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "filename": PDF_PATH.name,
        "file_size": file_size,
        "sha256": pdf_hash,
        "page_count": page_count,
        "text_length": text_length,
        "chapter_count": chapter_count,
        "parser_result": parser_result,
        "pdf_removed": pdf_removed,
        "status": status,
    }


def main() -> int:
    cfg = load_config()
    scanned = scan_chapter_range()

    if not PDF_PATH.is_file():
        # No temp PDF: allow success if chapters + manifest already complete.
        man = load_manifest()
        if (
            man.get("parser_result") == "ok"
            and scanned is not None
            and man.get("downloaded_start") is not None
        ):
            print("No changes detected.")
            print(
                f"Existing chapters: {man['downloaded_start']}-{man['downloaded_end']} "
                f"({man.get('chapter_count', scanned[2])} files)"
            )
            return 0
        print(f"Missing PDF: {PDF_PATH.relative_to(ROOT).as_posix()}")
        print("Run scripts/penana_download.py first (requires pdf_url in config).")
        return 1

    pdf_hash = sha256_file(PDF_PATH)
    prev = load_manifest()
    if (
        prev.get("sha256") == pdf_hash
        and TXT_PATH.is_file()
        and scanned is not None
        and prev.get("parser_result") == "ok"
    ):
        print("No changes detected.")
        return 0

    try:
        text, meta = pdf_to_text(PDF_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"parser error: {exc}", file=sys.stderr)
        # Keep PDF for debugging.
        prev["parser_result"] = "error"
        if prev:
            save_manifest(prev)
        return 1

    TXT_PATH.write_text(text, encoding="utf-8")
    print(
        f"TXT written: {TXT_PATH.relative_to(ROOT).as_posix()} "
        f"({meta['text_length']} chars, {meta['page_count']} pages)"
    )

    chapters = split_chapters(text)
    if not chapters:
        print("parser error: no chapters detected; keeping PDF.", file=sys.stderr)
        prev["parser_result"] = "error"
        if prev:
            save_manifest(prev)
        return 1

    write_chapters(chapters)
    print(f"chapters written: {len(chapters)} -> {CHAPTERS_DIR.relative_to(ROOT).as_posix()}")

    start = min(n for n, _, _ in chapters)
    end = max(n for n, _, _ in chapters)
    man = build_manifest(
        pdf_hash=pdf_hash,
        file_size=PDF_PATH.stat().st_size,
        page_count=meta["page_count"],
        text_length=meta["text_length"],
        chapter_count=len(chapters),
        start=start,
        end=end,
        cfg=cfg,
        parser_result="ok",
        pdf_removed=prev.get("pdf_removed", False),
    )
    # Preserve prior download provenance if re-parsing same file.
    if prev.get("downloaded_at") and prev.get("sha256") == pdf_hash:
        man["downloaded_at"] = prev["downloaded_at"]
    save_manifest(man)
    print(f"manifest written: {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    print(f"range            : downloaded {start}-{end} ({len(chapters)} chapters), status={man['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
