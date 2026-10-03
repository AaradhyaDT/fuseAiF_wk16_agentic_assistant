"""Deterministic self-check gate applied to every ``final_answer`` before it is accepted.

The verifier is plain code, not a second LLM call. That sidesteps the self-verification paradox
(the same model grading its own answer) for the properties that *can* be checked mechanically:
citation provenance and consistency between the claimed evidence and what the tools returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .trace import Trajectory


def _norm(doc: str) -> str:
    doc = str(doc).strip().removeprefix("doc:").removeprefix("[doc:").rstrip("]").strip()
    return Path(doc).name


def verify_final(args: dict[str, Any], trajectory: Trajectory) -> list[str]:
    """Return a list of human-readable problems; empty list means the answer is accepted."""
    problems: list[str] = []
    answer = str(args.get("answer", "")).strip()
    citations = [_norm(c) for c in args.get("citations", []) or [] if str(c).strip()]
    sufficient = bool(args.get("evidence_sufficient", False))

    if not answer:
        problems.append("answer is empty")

    retrieved = trajectory.retrieved_sources()
    unknown = sorted({c for c in citations if c not in retrieved})
    if unknown:
        seen = ", ".join(sorted(retrieved)) or "none"
        problems.append(
            f"citations {unknown} were never returned by a successful search/read in this run "
            f"(retrieved so far: {seen})"
        )

    evidence = trajectory.evidence_steps()
    if sufficient:
        if not citations:
            problems.append("evidence_sufficient=true but no citations were given")
        if evidence and not any(s.ok for s in evidence):
            problems.append(
                "evidence_sufficient=true but every evidence tool call failed; either retry "
                "another way or answer with evidence_sufficient=false"
            )
        if not evidence:
            problems.append("evidence_sufficient=true but no evidence tool was called")
    return problems


def normalise_citations(citations: list[Any]) -> list[str]:
    return list(dict.fromkeys(_norm(c) for c in citations or [] if str(c).strip()))
