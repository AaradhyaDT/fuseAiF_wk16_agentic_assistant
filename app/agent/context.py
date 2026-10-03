"""Context engineering for the agentic loop.

Three mechanisms, all applied inside :class:`app.agent.loop.AgentLoop` when it rebuilds the
prompt before every LLM call:

1. **Tool-result clearing + structured external notes** (primary). Raw retrieval output from
   older tool rounds is replaced with one-line stubs; durable facts survive only through the
   ``take_note`` scratchpad, which is re-rendered as a compact ``NOTES`` block.
2. **Retrieval capping** — top-k, relevance floor, and snippet truncation on every search.
3. **Progressive disclosure via Skills** — only ``name: description`` lines are in the initial
   prompt; the full ``SKILL.md`` body enters context only when the model calls ``load_skill``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- notes


@dataclass
class Note:
    fact: str
    source: str
    step: int


class NotesStore:
    """Ordered, de-duplicated external scratchpad that survives tool-result clearing."""

    def __init__(self, max_chars: int = 1500) -> None:
        self.max_chars = max_chars
        self._notes: list[Note] = []

    def add(self, fact: str, source: str, step: int) -> str:
        fact = " ".join(str(fact).split())[:300]
        source = str(source).strip()[:80] or "unspecified"
        if not fact:
            return "error: empty note ignored"
        key = fact.lower()
        if any(n.fact.lower() == key for n in self._notes):
            return "note already recorded"
        self._notes.append(Note(fact, source, step))
        return f"noted ({len(self._notes)} notes total)"

    def __len__(self) -> int:
        return len(self._notes)

    def render(self) -> str:
        if not self._notes:
            return "(no notes yet)"
        lines = [f"- {n.fact} [doc:{n.source}]" for n in self._notes]
        # Keep the most recent notes if over budget: drop from the oldest end.
        while lines and sum(len(x) + 1 for x in lines) > self.max_chars:
            lines.pop(0)
        return "\n".join(lines)

    def to_list(self) -> list[dict[str, Any]]:
        return [{"fact": n.fact, "source": n.source, "step": n.step} for n in self._notes]


# --------------------------------------------------------------------------- retrieval capping


def cap_retrieval(
    hits: list[dict[str, Any]], *, k: int, min_relevance: float, max_chars: int
) -> list[dict[str, Any]]:
    """Keep at most ``k`` hits above ``min_relevance``, each truncated to ``max_chars``."""
    capped = []
    for h in hits:
        relevance = max(0.0, 1.0 - float(h.get("distance", 1.0)))
        if relevance < min_relevance:
            continue
        text = " ".join(str(h.get("text", "")).split())
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
        capped.append({"source": h.get("source", "unknown"), "relevance": relevance, "text": text})
        if len(capped) >= k:
            break
    return capped


def format_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "no matching documents above the relevance floor"
    return "\n\n".join(
        f"[{i}] doc_id={h['source']} relevance={h['relevance']:.2f}\n{h['text']}"
        for i, h in enumerate(hits, 1)
    )


# --------------------------------------------------------------------------- tool-result clearing


@dataclass
class ToolRound:
    """One assistant turn with tool calls plus the tool messages answering it."""

    assistant: dict[str, Any]
    tool_messages: list[dict[str, Any]] = field(default_factory=list)
    stubs: list[str] = field(default_factory=list)


def make_stub(tool: str, args: dict[str, Any], result: str, sources: list[str]) -> str:
    """One-line replacement for a cleared tool result."""
    arg_txt = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in args.items() if k != "rationale")
    head = f"[cleared] {tool}({arg_txt})"
    if sources:
        uniq = list(dict.fromkeys(sources))
        return f"{head} -> {len(sources)} hit(s) from {', '.join(uniq)}; facts kept only in NOTES"
    first = " ".join(result.split())[:120]
    return f"{head} -> {first}"


def render_transcript(
    rounds: list[ToolRound], *, enable_clearing: bool, keep_last: int
) -> tuple[list[dict[str, Any]], int]:
    """Flatten tool rounds to OpenAI messages, stubbing all but the last ``keep_last`` rounds.

    Returns ``(messages, cleared_count)``.
    """
    messages: list[dict[str, Any]] = []
    cleared = 0
    cutoff = len(rounds) - max(0, keep_last)
    for idx, rnd in enumerate(rounds):
        messages.append(rnd.assistant)
        stale = enable_clearing and idx < cutoff
        for msg, stub in zip(rnd.tool_messages, rnd.stubs, strict=True):
            if stale and msg["content"] != stub:
                messages.append({**msg, "content": stub})
                cleared += 1
            else:
                messages.append(msg)
    return messages, cleared


# --------------------------------------------------------------------------- skills

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str


class SkillRegistry:
    """Loads ``skills/<name>/SKILL.md`` files; exposes index lines and full bodies separately."""

    def __init__(self, root: str | Path) -> None:
        self.skills: dict[str, Skill] = {}
        base = Path(root)
        if not base.exists():
            return
        for path in sorted(base.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            match = _FRONTMATTER.match(text.replace("\r\n", "\n"))
            if not match:
                continue
            meta: dict[str, str] = {}
            for line in match.group(1).splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"')
            name = meta.get("name") or path.parent.name
            self.skills[name] = Skill(name, meta.get("description", ""), match.group(2).strip())

    def index(self) -> str:
        if not self.skills:
            return "(no skills installed)"
        return "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())

    def load(self, name: str) -> str | None:
        skill = self.skills.get(str(name).strip())
        return skill.body if skill else None
