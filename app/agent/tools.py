"""Tool surface exposed to the agent, plus argument validation shared with the eval harness."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tools import calculate
from .context import NotesStore, SkillRegistry, cap_retrieval, format_hits

_RATIONALE = {
    "type": "string",
    "description": "One short sentence: why this action is the right next step.",
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {**properties, "rationale": _RATIONALE},
                "required": [*required, "rationale"],
            },
        },
    }


AGENT_TOOL_SPECS: list[dict] = [
    _fn(
        "search_knowledge_base",
        "Semantic search over the project knowledge base. Returns up to 4 capped snippets, each "
        "tagged with doc_id and relevance. Re-run with a refined query if evidence is weak.",
        {"query": {"type": "string", "description": "Focused search query."}},
        ["query"],
    ),
    _fn(
        "read_document",
        "Read one knowledge-base document in full (or a single section by heading). Use it to "
        "confirm a snippet against its source or to check dates/versions.",
        {
            "doc_id": {"type": "string", "description": "Exact doc_id, e.g. release_notes.md"},
            "section": {
                "type": "string",
                "description": "Optional heading text to return only that section.",
            },
        },
        ["doc_id"],
    ),
    _fn(
        "calculator",
        "Evaluate an arithmetic expression (+ - * / // % **). Use numbers taken from evidence.",
        {"expression": {"type": "string"}},
        ["expression"],
    ),
    _fn("current_datetime", "Return the current UTC date and time (ISO 8601).", {}, []),
    _fn(
        "take_note",
        "Record one verified fact with its source in the external NOTES scratchpad. Raw tool "
        "results are cleared from context after the next step; notes are kept.",
        {"fact": {"type": "string"}, "doc_id": {"type": "string"}},
        ["fact", "doc_id"],
    ),
    _fn(
        "load_skill",
        "Load the full instructions of a skill listed in SKILLS when it is relevant.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _fn(
        "ask_user",
        "Ask the user ONE clarifying question when the request is ambiguous. Ends this turn.",
        {"question": {"type": "string"}},
        ["question"],
    ),
    _fn(
        "final_answer",
        "Submit the final answer. It is verified: every citation must be a doc_id returned by a "
        "successful search_knowledge_base/read_document call in this conversation.",
        {
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence_sufficient": {
                "type": "boolean",
                "description": "false if tools failed or the knowledge base lacks the answer.",
            },
        },
        ["answer", "citations", "confidence", "evidence_sufficient"],
    ),
]

TOOL_SCHEMAS: dict[str, dict] = {
    s["function"]["name"]: s["function"]["parameters"] for s in AGENT_TOOL_SPECS
}
TERMINAL_TOOLS = {"final_answer", "ask_user"}
EVIDENCE_TOOLS = {"search_knowledge_base", "read_document"}
CONTEXT_TOOLS = {"take_note", "load_skill"}

_JSON_TYPES = {
    "string": str,
    "boolean": bool,
    "array": list,
    "object": dict,
    "number": (int, float),
    "integer": int,
}


def validate_args(name: str, args: Any) -> list[str]:
    """Minimal JSON-schema check (required keys, primitive types, enums, non-empty strings)."""
    schema = TOOL_SCHEMAS.get(name)
    if schema is None:
        return [f"unknown tool '{name}'"]
    if not isinstance(args, dict):
        return ["arguments are not a JSON object"]
    problems = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key == "rationale":
            continue  # rationale is requested for traces but never blocks execution
        if key not in args:
            problems.append(f"missing required argument '{key}'")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            continue
        expected = _JSON_TYPES.get(spec.get("type", ""), object)
        if not isinstance(value, expected) or (
            spec.get("type") in {"number", "integer"} and isinstance(value, bool)
        ):
            problems.append(f"argument '{key}' should be {spec.get('type')}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"argument '{key}' must be one of {spec['enum']}")
        if spec.get("type") == "string" and key in schema.get("required", []) and not value.strip():
            problems.append(f"argument '{key}' is empty")
    return problems


@dataclass
class ToolOutcome:
    result: str
    ok: bool = True
    error: str | None = None
    kind: str = "tool"
    sources: list[str] = field(default_factory=list)


class ToolUnavailableError(RuntimeError):
    pass


def _split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading, buf = "(intro)", []
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s", line):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = line.lstrip("#").strip(), [line]
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))
    return sections


class AgentToolbox:
    """Executes non-terminal agent tools. Pure/sync work; the loop wraps calls with a timeout."""

    def __init__(
        self,
        *,
        retriever: Any,
        docs_dir: str | Path,
        notes: NotesStore,
        skills: SkillRegistry,
        retrieval_k: int = 4,
        min_relevance: float = 0.15,
        snippet_chars: int = 600,
        doc_max_chars: int = 3000,
    ) -> None:
        self.retriever = retriever
        self.docs_dir = Path(docs_dir)
        self.notes = notes
        self.skills = skills
        self.retrieval_k = retrieval_k
        self.min_relevance = min_relevance
        self.snippet_chars = snippet_chars
        self.doc_max_chars = doc_max_chars

    # -- individual tools -------------------------------------------------
    def search_knowledge_base(self, query: str, **_: Any) -> ToolOutcome:
        if self.retriever is None:
            raise ToolUnavailableError("retriever not configured")
        raw = self.retriever.retrieve(query, k=max(self.retrieval_k * 2, 6))
        hits = cap_retrieval(
            raw, k=self.retrieval_k, min_relevance=self.min_relevance, max_chars=self.snippet_chars
        )
        return ToolOutcome(format_hits(hits), kind="evidence", sources=[h["source"] for h in hits])

    def available_docs(self) -> list[str]:
        if not self.docs_dir.exists():
            return []
        return sorted(p.name for p in self.docs_dir.iterdir() if p.suffix in {".md", ".txt"})

    def read_document(self, doc_id: str, section: str | None = None, **_: Any) -> ToolOutcome:
        name = Path(str(doc_id).strip()).name  # strips any path components -> no traversal
        if name not in self.available_docs():
            return ToolOutcome(
                f"error: unknown doc_id '{doc_id}'. Available: {', '.join(self.available_docs())}",
                ok=False,
                error="unknown_doc",
                kind="evidence",
            )
        text = (self.docs_dir / name).read_text(encoding="utf-8")
        if section:
            wanted = section.lower().strip("# ").strip()
            matches = [body for head, body in _split_sections(text) if wanted in head.lower()]
            if matches:
                text = "\n\n".join(matches)
            else:
                heads = [h for h, _ in _split_sections(text)]
                return ToolOutcome(
                    f"error: section '{section}' not found in {name}. Headings: {heads}",
                    ok=False,
                    error="unknown_section",
                    kind="evidence",
                )
        if len(text) > self.doc_max_chars:
            text = text[: self.doc_max_chars] + "\n…[truncated]"
        return ToolOutcome(f"doc_id={name}\n{text}", kind="evidence", sources=[name])

    def calculator(self, expression: str, **_: Any) -> ToolOutcome:
        value = calculate(str(expression))
        return ToolOutcome(value, ok=not value.startswith("error"), error=None)

    def current_datetime(self, **_: Any) -> ToolOutcome:
        return ToolOutcome(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def take_note(self, fact: str, doc_id: str, step: int = 0, **_: Any) -> ToolOutcome:
        msg = self.notes.add(fact, doc_id, step)
        return ToolOutcome(msg, ok=not msg.startswith("error"), kind="context")

    def load_skill(self, name: str, **_: Any) -> ToolOutcome:
        body = self.skills.load(name)
        if body is None:
            return ToolOutcome(
                f"error: no skill named '{name}'. Available: {list(self.skills.skills)}",
                ok=False,
                error="unknown_skill",
                kind="context",
            )
        return ToolOutcome(f"SKILL {name}:\n{body}", kind="context")

    # -- dispatch ---------------------------------------------------------
    def run(self, name: str, args: dict[str, Any], *, step: int = 0) -> ToolOutcome:
        handler = getattr(self, name, None)
        if name in TERMINAL_TOOLS or name not in TOOL_SCHEMAS or handler is None:
            return ToolOutcome(f"error: unknown tool '{name}'", ok=False, error="unknown_tool")
        problems = validate_args(name, args)
        if problems:
            return ToolOutcome(
                "error: invalid arguments: " + "; ".join(problems),
                ok=False,
                error="invalid_args",
                kind="evidence" if name in EVIDENCE_TOOLS else "tool",
            )
        kwargs = {k: v for k, v in args.items() if k != "rationale"}
        if name == "take_note":
            kwargs["step"] = step
        try:
            return handler(**kwargs)
        except ToolUnavailableError as exc:
            return ToolOutcome(
                json.dumps({"error": f"tool unavailable: {exc}"}),
                ok=False,
                error="tool_unavailable",
                kind="evidence" if name in EVIDENCE_TOOLS else "tool",
            )
        except Exception as exc:
            return ToolOutcome(
                f"error: {type(exc).__name__}: {exc}",
                ok=False,
                error="exception",
                kind="evidence" if name in EVIDENCE_TOOLS else "tool",
            )
