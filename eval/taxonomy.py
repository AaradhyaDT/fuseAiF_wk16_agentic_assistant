"""Three-tier failure taxonomy for agentic evaluation runs.

Classifies test run outcomes into:
- SUCCESS
- HARD_FAILURE
- SOFT_FAILURE
- CASCADING_SOFT_FAILURE
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.agent.trace import AgentResult, Step, TerminationReason


class FailureCategory(StrEnum):
    NONE = "none"
    HARD = "hard"
    SOFT = "soft"
    CASCADING_SOFT = "cascading_soft"


@dataclass
class FailureRecord:
    case_id: str
    category: FailureCategory
    reason: str
    root_cause_step: int | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": str(self.category),
            "reason": self.reason,
            "root_cause_step": self.root_cause_step,
            "details": self.details or {},
        }


def classify_outcome(
    case: dict[str, Any],
    result: AgentResult,
    *,
    passed: bool,
    correctness_issues: list[str],
) -> FailureRecord:
    """Analyze agent result and classify failure mode if passed is False."""
    case_id = case.get("id", "unknown")
    if passed:
        return FailureRecord(case_id, FailureCategory.NONE, "Success")

    # 1. Hard Failure Check
    if result.termination_reason in {
        TerminationReason.MAX_ITERATIONS,
        TerminationReason.BUDGET_EXHAUSTED,
        TerminationReason.LOOP_DETECTED,
        TerminationReason.PROVIDER_FAILURE,
    }:
        return FailureRecord(
            case_id,
            FailureCategory.HARD,
            f"Hard termination: {result.termination_reason}",
            details={
                "iterations": result.iterations,
                "termination_reason": str(result.termination_reason),
            },
        )

    if result.status == "failed":
        return FailureRecord(
            case_id,
            FailureCategory.HARD,
            f"Execution failed status: {result.answer[:120]}",
        )

    # Check for invalid tool names
    for s in result.trajectory.steps:
        if s.error in {"unknown_tool"}:
            return FailureRecord(
                case_id,
                FailureCategory.HARD,
                f"Invoked invalid tool at step {s.step}: {s.tool}",
                root_cause_step=s.step,
            )

    # 2. Cascading Soft Failure Check
    # Look for intermediate tool failures that the agent blindly built upon
    intermediate_errors: list[Step] = [
        s
        for s in result.trajectory.steps
        if not s.ok and s.kind != "terminal" and s.error not in {"unknown_tool"}
    ]
    if intermediate_errors:
        first_err = intermediate_errors[0]
        return FailureRecord(
            case_id,
            FailureCategory.CASCADING_SOFT,
            (
                f"Cascading error: step {first_err.step}"
                f" ({first_err.tool}) errored"
                f" ({first_err.error}), propagating"
                " to flawed final answer"
            ),
            root_cause_step=first_err.step,
            details={
                "failed_tool": first_err.tool,
                "error": first_err.error,
                "correctness_issues": correctness_issues,
            },
        )

    # Check for empty retrieval results that were not recovered
    for s in result.trajectory.steps:
        if s.tool == "search_knowledge_base" and "no matching documents" in s.result.lower():
            # If the query expected answers from the corpus, this is a cascading cause
            if case.get("required_sources"):
                return FailureRecord(
                    case_id,
                    FailureCategory.CASCADING_SOFT,
                    (
                        f"Cascading retrieval failure:"
                        f" step {s.step} yielded no matching"
                        " documents for query, leading"
                        " to incomplete answer"
                    ),
                    root_cause_step=s.step,
                    details={
                        "search_query": s.args.get("query"),
                        "correctness_issues": correctness_issues,
                    },
                )

    # 3. Standard Soft Failure
    # Terminal output was produced, but answer was inaccurate, missing facts, or wrong citations
    return FailureRecord(
        case_id,
        FailureCategory.SOFT,
        f"Soft failure: {'; '.join(correctness_issues)}",
        details={"correctness_issues": correctness_issues},
    )
