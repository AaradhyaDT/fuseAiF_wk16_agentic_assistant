"""Structured trace records for the agentic loop.

Every step the agent takes is captured as ``{step, tool, args, result, reasoning, ...}`` so the
evaluation harness (and later MLflow tracing in W17) can replay exactly what happened.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class TerminationReason(StrEnum):
    ANSWERED = "answered"
    ANSWERED_UNVERIFIED = "answered_unverified"
    ASKED_USER = "asked_user"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LOOP_DETECTED = "loop_detected"
    PROVIDER_FAILURE = "provider_failure"


# Terminations that leave the user without a usable, verified answer.
HARD_STOP_REASONS = {
    TerminationReason.MAX_ITERATIONS,
    TerminationReason.BUDGET_EXHAUSTED,
    TerminationReason.LOOP_DETECTED,
    TerminationReason.PROVIDER_FAILURE,
}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    estimated: bool = False

    def add(self, raw: dict[str, Any]) -> None:
        self.prompt_tokens += int(raw.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(raw.get("completion_tokens", 0) or 0)
        self.reasoning_tokens += int(raw.get("reasoning_tokens", 0) or 0)
        total = int(raw.get("total_tokens", 0) or 0)
        if not total:
            total = int(raw.get("prompt_tokens", 0) or 0) + int(
                raw.get("completion_tokens", 0) or 0
            )
        self.total_tokens += total
        self.llm_calls += 1
        self.estimated = self.estimated or bool(raw.get("estimated"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Step:
    """One tool invocation (or terminal action) chosen by the model."""

    step: int
    iteration: int
    tool: str
    args: dict[str, Any]
    result: str
    reasoning: str = ""
    ok: bool = True
    error: str | None = None
    kind: str = "tool"  # tool | evidence | context | terminal | guard
    sources: list[str] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMCall:
    iteration: int
    provider: str
    usage: dict[str, Any]
    prompt_chars: int
    latency_ms: int


@dataclass
class Trajectory:
    query: str
    steps: list[Step] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    def next_index(self) -> int:
        return len(self.steps) + 1

    def evidence_steps(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "evidence"]

    def retrieved_sources(self) -> set[str]:
        """Sources returned by *successful* evidence steps in this run."""
        found: set[str] = set()
        for s in self.evidence_steps():
            if s.ok:
                found.update(s.sources)
        return found

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "steps": [s.to_dict() for s in self.steps],
            "llm_calls": [asdict(c) for c in self.llm_calls],
        }


@dataclass
class AgentResult:
    answer: str
    status: str  # answered | needs_clarification | unverified | failed
    termination_reason: TerminationReason
    iterations: int
    trajectory: Trajectory
    usage: Usage
    citations: list[str] = field(default_factory=list)
    confidence: str = "low"
    evidence_sufficient: bool = False
    provider_used: str = "none"
    verification_failures: list[str] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "status": self.status,
            "termination_reason": str(self.termination_reason),
            "iterations": self.iterations,
            "citations": self.citations,
            "confidence": self.confidence,
            "evidence_sufficient": self.evidence_sufficient,
            "provider_used": self.provider_used,
            "verification_failures": self.verification_failures,
            "notes": self.notes,
            "usage": self.usage.to_dict(),
            "latency_ms": self.latency_ms,
            "trajectory": self.trajectory.to_dict(),
        }
