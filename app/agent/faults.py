"""Failure injection for the agent's evidence tools (used by tests and the eval harness).

Modes
-----
``tool_unavailable``
    *Both* evidence tools (search + read_document) report the vector store / doc store is down.
    There is no legitimate way to recover, so the correct behaviour is to say so
    (``evidence_sufficient=false``) instead of answering confidently from memory.
``malformed_retrieval``
    ``search_knowledge_base`` returns truncated, garbled JSON with no parseable doc_ids while
    reporting success. ``read_document`` still works, so a careful agent can recover.
``timeout``
    ``search_knowledge_base`` hangs past the per-tool timeout. ``read_document`` still works.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .tools import AgentToolbox, ToolOutcome

FAULT_MODES = ("tool_unavailable", "malformed_retrieval", "timeout")

_MALFORMED = (
    '{"hits": [{"doc_id": null, "relevance": NaN, "text": "\\u0000\\u0000\\ufffd\\ufffd'
    'chun\\ufffd 0x7f3a … vect0r_dim_mismatch (384 != 768) … ]]}, {"doc_id": "", '
    '"text": "lorem \\ufffd\\ufffd'
)


class FaultInjector:
    """Wraps :class:`AgentToolbox` and corrupts the targeted tools according to ``mode``."""

    def __init__(self, toolbox: AgentToolbox, mode: str, *, timeout_s: float = 10.0) -> None:
        if mode and mode not in FAULT_MODES:
            raise ValueError(f"unknown fault mode {mode!r}; expected one of {FAULT_MODES}")
        self.toolbox = toolbox
        self.mode = mode
        self.timeout_s = timeout_s
        self.injected = 0

    def __getattr__(self, item: str) -> Any:  # delegate notes/skills/etc.
        return getattr(self.toolbox, item)

    def run(self, name: str, args: dict[str, Any], *, step: int = 0) -> ToolOutcome:
        if self.mode == "tool_unavailable" and name in {"search_knowledge_base", "read_document"}:
            self.injected += 1
            return ToolOutcome(
                json.dumps({"error": "tool unavailable: knowledge store connection refused"}),
                ok=False,
                error="tool_unavailable",
                kind="evidence",
            )
        if self.mode == "malformed_retrieval" and name == "search_knowledge_base":
            self.injected += 1
            # Reports success (no error flag) — the corruption is in the payload itself.
            return ToolOutcome(_MALFORMED, ok=True, kind="evidence", sources=[])
        if self.mode == "timeout" and name == "search_knowledge_base":
            self.injected += 1
            time.sleep(self.timeout_s + 0.5)
        return self.toolbox.run(name, args, step=step)
