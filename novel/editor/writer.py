#!/usr/bin/env python3
"""Novel Writer Agent (phase 3C): Context -> Draft pipeline.

Pipeline (never bypassed):
    User -> context_builder.py -> Context -> WriterProvider -> Draft
    -> draft-validator.py -> novel/drafts/

    python novel/editor/writer.py --request "續寫第60章" --provider mock
    python novel/editor/writer.py --request "寫星星與沐寒戰鬥" \\
        --output novel/drafts/battle-test.md --provider mock

Safety: drafts may ONLY be written under novel/drafts/. Never touches
novel/chapters/**, novel/canon/**, novel/plot/**, novel/review/**.
Phase 3C ships mock + openai-compatible providers; mock emits
[MOCK DRAFT] only and never writes real fiction.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urlrequest

EDITOR_DIR = Path(__file__).resolve().parent
ROOT = EDITOR_DIR.parent.parent
DRAFTS_DIR = ROOT / "novel" / "drafts"

sys.path.insert(0, str(EDITOR_DIR))
import context_builder as cb  # noqa: E402  (must go through Context Builder)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class ProviderNotConfigured(Exception):
    pass


class WriterProvider:
    name = "base"

    def generate(self, context: dict, instruction: str) -> str:
        raise NotImplementedError


class MockProvider(WriterProvider):
    """Test-only provider. Emits a [MOCK DRAFT] outline, never fiction."""
    name = "mock"

    def generate(self, context: dict, instruction: str) -> str:
        lines = ["[MOCK DRAFT]", ""]
        lines.append(f"Request: {context.get('request', '')}")
        lines.append(f"Task type: {context.get('task_type', '')}")
        entities = (context.get("detected") or {}).get("entities", [])
        lines.append(f"Entities: {', '.join(entities) if entities else '(none)'}")
        ncanon = sum(len(v) for v in context.get("canon", {}).values())
        nplot = sum(len(v) for v in context.get("plot", {}).values())
        lines.append(f"Context items: canon={ncanon} plot={nplot}")
        lines.append("")
        lines.append("本草稿為 Mock 佔位，不包含真正的小說正文。")
        lines.append("正式寫作需由作者確認 Context 後再接真正的 WriterProvider。")
        return "\n".join(lines) + "\n"


class OpenAICompatibleProvider(WriterProvider):
    """OpenAI-compatible chat API. Configured purely via environment:

        LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL / LLM_API_KEY
    """
    name = "openai-compatible"

    def __init__(self) -> None:
        self.base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        missing = [k for k, v in
                   (("LLM_BASE_URL", self.base_url), ("LLM_MODEL", self.model),
                    ("LLM_API_KEY", self.api_key)) if not v]
        if missing:
            raise ProviderNotConfigured(
                "LLM provider is not configured. "
                f"Missing: {', '.join(missing)}."
            )

    def generate(self, context: dict, instruction: str) -> str:
        prompt = (EDITOR_DIR / "writer-prompt.md").read_text(encoding="utf-8")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content":
                    f"Instruction: {instruction}\n\nContext:\n"
                    + json.dumps(context, ensure_ascii=False)},
            ],
        }
        req = urlrequest.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


PROVIDERS = {"mock": MockProvider, "openai-compatible": OpenAICompatibleProvider}


# ---------------------------------------------------------------------------
# Draft assembly
# ---------------------------------------------------------------------------

ADOPT_RES = [re.compile(p) for p in
             ["採用", "使用", "同意採用", "批准", "就用"]]


def detect_adopted(request: str, proposed: list[dict]) -> list[str]:
    """Proposed items explicitly adopted by the author for THIS run only."""
    adopted: list[str] = []
    if not any(p.search(request) for p in ADOPT_RES):
        return adopted
    nreq = cb.norm(request)
    for item in proposed:
        pid = item["id"]
        title_keys = [w for w in re.split(r"[／/、，,（）()\[\] ]+", item["title"]) if w]
        if pid.lower() in nreq or any(cb.norm(t) and cb.norm(t) in nreq for t in title_keys):
            adopted.append(pid)
    return adopted


QUESTION_SUFFIX = ["是什麼", "是什么", "是啥", "介紹", "介绍", "如何", "嗎", "吗", "？", "?"]


def request_core(nreq: str) -> str:
    core = nreq
    changed = True
    while changed:
        changed = False
        for suf in QUESTION_SUFFIX:
            if core.endswith(suf) and len(core) > len(suf):
                core = core[: -len(suf)]
                changed = True
    return core


def detect_affected(request: str, entities: list[str], conflicts: list[dict]) -> list[dict]:
    """Conflicts that directly affect the current plot (situation B)."""
    nreq = cb.norm(request)
    core = request_core(nreq)
    ent_aliases: set[str] = set()
    for _cat, table in cb.ENTITIES.items():
        for canon, als in table.items():
            if canon in entities:
                ent_aliases.update(cb.norm(a) for a in als)
    affected = []
    for c in conflicts:
        blob = cb.norm(c["id"] + c["title"] + c.get("excerpt", ""))
        if any(a and a in blob for a in ent_aliases):
            affected.append(c)
        elif len(core) >= 2 and core in blob:
            affected.append(c)
    return affected


def infer_target(context: dict) -> tuple[str, list[str]]:
    cont = (context.get("detected") or {}).get("continue_next")
    chapters = (context.get("detected") or {}).get("chapters", [])
    if cont is not None:
        return f"chapter-{cont:03d}", [f"{c:03d}" for c in chapters]
    if chapters:
        return f"chapter-{chapters[-1]:03d}-analysis", [f"{c:03d}" for c in chapters]
    story = context.get("story_state") or {}
    last = story.get("last_chapter") or {}
    srcs = [s.split("/")[-1].replace(".md", "") for s in last.get("source", [])]
    return "standalone", srcs


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True, text=True,
                             timeout=15)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_draft(request: str, provider_name: str = "mock",
                max_items: int = 40) -> tuple[dict, str]:
    """User -> Context Builder -> Writer. Returns (draft_dict, body)."""
    context = cb.build_context(request, max_items=max_items)
    provider_cls = PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ProviderNotConfigured(
            f"LLM provider is not configured. Unknown provider: {provider_name}."
        )
    provider = provider_cls()

    insufficient: list[str] = []
    if context["task_type"] == "UNKNOWN" or (
            not any(context["canon"].values()) and not any(context["plot"].values())):
        if context["task_type"] in ("WRITE", "CONTINUE", "BATTLE", "UNKNOWN"):
            missing = []
            if not any(context["canon"].values()):
                missing += ["character information", "ability information"]
            if not any(context["plot"].values()):
                missing += ["timeline information"]
            if missing:
                insufficient = missing

    proposed = context["review"]["proposed"]
    # adoption is checked against the FULL catalog (not the truncated
    # context slice) and adopted items are force-included as high relevance.
    catalog = cb.parse_review_items("proposed.md", "P")
    adopted = detect_adopted(
        request, [{"id": c["id"], "title": c["title"]} for c in catalog])
    have = {p["id"] for p in proposed}
    for c in catalog:
        if c["id"] in adopted and c["id"] not in have:
            proposed.append({
                "id": c["id"], "title": c["title"] or c["id"],
                "status": "PROPOSED", "confidence": "",
                "source": ["novel/review/proposed.md"],
                "reason": "作者本次明確採用，僅限本次生成使用；不要自動修改 Canon。",
                "relevance": "high",
            })
    affected = detect_affected(
        request, (context.get("detected") or {}).get("entities", []),
        context["review"]["conflicts"])
    needs = bool(affected) or bool(insufficient)

    if insufficient:
        body = ("[INSUFFICIENT_CONTEXT]\nmissing:\n"
                + "".join(f"- {m}\n" for m in insufficient))
    else:
        body = provider.generate(context, instruction=request)

    if affected:
        block = "".join(
            f"\n[NEEDS_AUTHOR_DECISION]\nConflict: {c['id']}\n"
            f"Reason: unresolved conflict directly affects this plot; "
            f"author decision required before writing this part.\n"
            for c in affected)
        body = body.rstrip("\n") + "\n" + block

    target, source_chapters = infer_target(context)
    draft_id = f"draft-{target}-001"
    draft = {
        "draft_id": draft_id,
        "target": target,
        "request": request,
        "request_type": context["task_type"],
        "status": "DRAFT",
        "canon_version": git_head(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "content": body,
        "needs_author_decision": needs,
        "warnings": list(context.get("warnings", [])),
        "conflicts_used": [c["id"] for c in context["review"]["conflicts"]],
        "proposed_used": [p["id"] for p in proposed if p["id"] in adopted],
        "proposed_mentioned": [p["id"] for p in proposed],
        "inferred_used": [i["id"] for i in context["review"]["inferred"]],
        "entities_used": (context.get("detected") or {}).get("entities", []),
        "new_settings": [],
        "source_chapters": source_chapters,
        "source_trace": context.get("source_trace", []),
    }
    if insufficient:
        draft["warnings"].append("[INSUFFICIENT_CONTEXT] writer refused to invent canon.")
    return draft, body


# ---------------------------------------------------------------------------
# Frontmatter rendering (machine-readable, no external deps)
# ---------------------------------------------------------------------------

def _yaml_val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if not v or isinstance(v[0], dict):
            if not v:
                return "[]"
            return "\n" + "".join(_yaml_dict_block(d) for d in v)
        return "\n" + "".join(f'  - "{_flat(x)}"\n' for x in v)
    return f'"{_flat(v)}"'


def _flat(v) -> str:
    return str(v).replace(chr(34), chr(39)).replace("\n", " / ")


def _yaml_dict_block(d: dict) -> str:
    lines = []
    first = True
    for k, val in d.items():
        if isinstance(val, (list, dict)):
            val = "'" + json.dumps(val, ensure_ascii=False).replace("'", "’") + "'"
        else:
            val = f'"{_flat(val)}"'
        prefix = "  - " if first else "    "
        lines.append(f"{prefix}{k}: {val}\n")
        first = False
    return "".join(lines)


FRONTMATTER_KEYS = ["draft_id", "target", "request", "request_type", "status",
                    "canon_version", "generated_at", "needs_author_decision",
                    "conflicts_used", "proposed_used", "inferred_used",
                    "source_chapters", "warnings", "source_trace"]


def render_draft_file(draft: dict) -> str:
    fm = ["---"]
    for k in FRONTMATTER_KEYS:
        fm.append(f"{k}: {_yaml_val(draft.get(k))}")
    fm.append("---")
    return "\n".join(fm) + "\n\n" + draft["content"]


def resolve_output(path_str: str, draft_id: str) -> Path:
    """Outputs are allowed ONLY under novel/drafts/; bump version if taken."""
    p = (ROOT / path_str).resolve() if not Path(path_str).is_absolute() \
        else Path(path_str).resolve()
    if DRAFTS_DIR.resolve() not in p.parents and p.parent != DRAFTS_DIR.resolve():
        raise ValueError(f"Refusing to write outside novel/drafts/: {path_str}")
    if p.suffix != ".md":
        p = p.with_suffix(".md")
    if p.exists():
        m = re.match(r"^(.*-)(\d{3})(\.md)$", p.name)
        base, num = (m.group(1), int(m.group(2))) if m else (p.stem + "-", 1)
        while True:
            num += 1
            cand = p.with_name(f"{base}{num:03d}.md")
            if not cand.exists():
                return cand
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Novel Writer Agent (draft pipeline).")
    ap.add_argument("--request", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "mock"))
    ap.add_argument("--max-items", type=int, default=40)
    ap.add_argument("--consistency", action="store_true",
                    help="run draft-validator + consistency checker after writing")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        draft, _body = build_draft(args.request, args.provider, args.max_items)
    except ProviderNotConfigured as exc:
        print(str(exc))
        return 2
    text = render_draft_file(draft)
    if args.output:
        try:
            out = resolve_output(args.output, draft["draft_id"])
        except ValueError as exc:
            print(str(exc))
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"draft written: {out.relative_to(ROOT).as_posix()}")
        if args.consistency:
            run_consistency_gate(out)
    else:
        if args.consistency:
            print("--consistency requires --output; skipping gate.")
        sys.stdout.write(text)
    return 0


def run_consistency_gate(draft_path: Path) -> int:
    """Optional post pipeline: validator -> consistency checker -> reports."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dv_gate", EDITOR_DIR / "draft-validator.py")
    assert spec and spec.loader
    dv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dv)
    spec2 = importlib.util.spec_from_file_location(
        "cc_gate", EDITOR_DIR / "consistency_checker.py")
    assert spec2 and spec2.loader
    cc = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(cc)
    fails, warns, new, _ = dv.validate(draft_path)
    print(f"validator: {len(fails)} failures, {len(warns)} warnings, "
          f"{len(new)} new settings")
    rep = cc.Checker(draft_path, None).run(cc.snapshot())
    stem = draft_path.with_suffix("")
    json_path = stem.parent / (stem.name + "-consistency.json")
    md_path = stem.parent / (stem.name + "-consistency.md")
    clean = json.loads(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "",
                              json.dumps(rep, ensure_ascii=False)))
    json_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    md_path.write_text(cc.to_markdown(clean), encoding="utf-8")
    print(f"consistency: {clean['status']} "
          f"(E{clean['summary']['errors']} W{clean['summary']['warnings']} "
          f"I{clean['summary']['info']})")
    print(f"reports: {json_path.name}, {md_path.name}")
    return 0 if clean["status"] != "ERROR" else 1


if __name__ == "__main__":
    sys.exit(main())
