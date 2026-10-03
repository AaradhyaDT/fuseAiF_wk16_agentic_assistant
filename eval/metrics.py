"""Deterministic metric evaluation for agentic evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.tools import validate_args
from app.agent.trace import AgentResult

from .pricing import calculate_cost
from .taxonomy import FailureRecord, classify_outcome


@dataclass
class CaseEvaluation:
    case_id: str
    category: str
    passed: bool
    terminal_matched: bool
    tool_correctness: float  # 0.0 - 1.0
    trajectory_length: int
    over_long: bool
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: float
    failure: FailureRecord
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "terminal_matched": self.terminal_matched,
            "tool_correctness": round(self.tool_correctness, 3),
            "trajectory_length": self.trajectory_length,
            "over_long": self.over_long,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "failure": self.failure.to_dict(),
            "issues": self.issues,
        }


def evaluate_case(case: dict[str, Any], result: AgentResult) -> CaseEvaluation:
    case_id = case.get("id", "unknown")
    category = case.get("category", "general")
    issues: list[str] = []

    # 1. Terminal Action Match
    expected_terminal = case.get("expected_terminal", "final_answer")
    actual_terminal = "ask_user" if result.status == "needs_clarification" else "final_answer"
    terminal_matched = expected_terminal == actual_terminal
    if not terminal_matched:
        msg = f"Expected terminal '{expected_terminal}', got '{actual_terminal}' ({result.status})"
        issues.append(msg)

    # 2. Required and Forbidden Tools
    tools_called = [s.tool for s in result.trajectory.steps]
    for req_t in case.get("required_tools", []):
        if req_t not in tools_called:
            issues.append(f"Missing required tool call: '{req_t}'")
    for forb_t in case.get("forbidden_tools", []):
        if forb_t in tools_called:
            issues.append(f"Invoked forbidden tool: '{forb_t}'")

    # 3. Required Sources Citation Check
    if expected_terminal == "final_answer":
        cited_set = set(result.citations)
        for req_src in case.get("required_sources", []):
            if req_src not in cited_set:
                issues.append(
                    f"Missing required citation: '{req_src}' (cited: {sorted(cited_set)})"
                )

    # 4. Text Invariant Checks (must_include_any & must_not_include)
    answer_text = result.answer.lower()
    for group in case.get("must_include_any", []):
        matched = any(needle.lower() in answer_text for needle in group)
        if not matched:
            issues.append(f"Answer missing mandatory keyword from group: {group}")

    for needle in case.get("must_not_include", []):
        if needle.lower() in answer_text:
            issues.append(f"Answer contains forbidden substring: '{needle}'")

    # 5. Tool Call Syntax & Semantic Correctness
    valid_calls = 0
    total_calls = len(result.trajectory.steps)
    for s in result.trajectory.steps:
        schema_errs = validate_args(s.tool, s.args)
        if not schema_errs and s.ok:
            valid_calls += 1
        elif schema_errs:
            issues.append(f"Tool {s.tool} invalid args: {'; '.join(schema_errs)}")

    tool_correctness = (valid_calls / total_calls) if total_calls > 0 else 1.0

    # 6. Trajectory Length & Over-long Flag
    trajectory_length = result.iterations
    max_reasonable = case.get("max_reasonable_steps", 6)
    over_long = trajectory_length > max_reasonable

    # 7. Token and Cost Accounting
    cost_usd = calculate_cost(
        result.provider_used,
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.reasoning_tokens,
    )

    passed = (len(issues) == 0) and terminal_matched
    failure = classify_outcome(case, result, passed=passed, correctness_issues=issues)

    return CaseEvaluation(
        case_id=case_id,
        category=category,
        passed=passed,
        terminal_matched=terminal_matched,
        tool_correctness=tool_correctness,
        trajectory_length=trajectory_length,
        over_long=over_long,
        prompt_tokens=result.usage.prompt_tokens,
        completion_tokens=result.usage.completion_tokens,
        reasoning_tokens=result.usage.reasoning_tokens,
        total_tokens=result.usage.total_tokens,
        cost_usd=cost_usd,
        failure=failure,
        issues=issues,
    )
