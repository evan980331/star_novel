#!/usr/bin/env python3
"""Audit novel source files: hash, metadata, content extraction (read-only)."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / "docs" / "audit"
TEXT_EXTS = {".docx", ".pdf", ".txt", ".md"}
IMG_EXTS = {".png"}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
# Do not treat previously generated analysis copies as source inputs.
SKIP_NAME_PREFIXES = ()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []

    # Walk body in document order so tables are not lost.
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = doc.element.body
    para_by_el = {p._element: p for p in doc.paragraphs}
    table_by_el = {t._element: t for t in doc.tables}

    for child in body.iterchildren():
        if child in para_by_el:
            p = para_by_el[child]
            text = p.text
            style = p.style.name if p.style is not None else ""
            if style and style.lower().startswith("heading"):
                lines.append(f"{'#' * min(int(style.split()[-1]) if style.split()[-1].isdigit() else 1, 6)} {text}")
            elif text.strip():
                lines.append(text)
            else:
                lines.append("")
        elif child in table_by_el:
            t = table_by_el[child]
            lines.append("[TABLE]")
            for row in t.rows:
                cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                lines.append(" | ".join(cells))
            lines.append("[/TABLE]")
    return "\n".join(lines)


def extract_pdf(path: Path) -> tuple[str, dict]:
    import fitz

    doc = fitz.open(str(path))
    parts: list[str] = []
    for i, page in enumerate(doc, start=1):
        parts.append(f"===== PAGE {i} =====\n{page.get_text()}")
    meta = {
        "page_count": doc.page_count,
        "text_length": sum(len(p) for p in parts),
    }
    doc.close()
    return "\n".join(parts), meta


def extract_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def png_info(path: Path) -> dict:
    data = path.read_bytes()
    info = {"format": "png"}
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        import struct

        w, h = struct.unpack(">II", data[16:24])
        info.update({"width": w, "height": h})
    return info


def main() -> int:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(ROOT).parts
        if any(p in SKIP_DIRS for p in rel_parts[:-1]):
            continue
        if path.name == Path(__file__).name:
            continue
        # skip our own analysis outputs under docs/audit
        if rel_parts[:2] == ("docs", "audit"):
            continue
        stat = path.stat()
        ext = path.suffix.lower()
        entry = {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "extension": ext,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": sha256_of(path),
            "readable": False,
            "notes": [],
        }
        try:
            if ext == ".docx":
                text = extract_docx(path)
                out = AUDIT_DIR / f"{path.stem}.txt"
                out.write_text(text, encoding="utf-8")
                entry.update(
                    readable=True,
                    extracted_chars=len(text),
                    extracted_to=out.relative_to(ROOT).as_posix(),
                )
            elif ext == ".pdf":
                text, meta = extract_pdf(path)
                out = AUDIT_DIR / f"{path.stem}_pdf_extract.txt"
                out.write_text(text, encoding="utf-8")
                entry.update(
                    readable=True,
                    extracted_chars=meta["text_length"],
                    page_count=meta["page_count"],
                    extracted_to=out.relative_to(ROOT).as_posix(),
                )
            elif ext in {".txt", ".md"}:
                text = extract_text_file(path)
                entry.update(readable=True, extracted_chars=len(text))
            elif ext in IMG_EXTS:
                entry.update(readable=True, image=png_info(path))
            else:
                entry["notes"].append("extension not content-checked")
        except Exception as exc:  # noqa: BLE001
            entry["notes"].append(f"extract failed: {exc}")
        results.append(entry)

    report = {
        "root": str(ROOT),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(results),
        "files": results,
    }
    out_json = AUDIT_DIR / "audit_report.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Scanned {len(results)} files under {ROOT}")
    for e in results:
        print(
            f"- {e['relative_path']} | {e['extension']} | {e['size']} bytes | "
            f"sha256={e['sha256'][:16]}... | readable={e['readable']}"
        )
        for n in e["notes"]:
            print(f"    note: {n}")
    print(f"JSON report: {out_json.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
