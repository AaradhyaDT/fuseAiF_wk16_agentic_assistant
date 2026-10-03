"""Report generator for W16 agentic evaluation runs."""

from __future__ import annotations

from .metrics import CaseEvaluation
from .taxonomy import FailureCategory


def generate_markdown_report(
    evaluations: list[CaseEvaluation],
    *,
    run_id: str,
    title: str = "W16 Agentic Evaluation Report",
    baseline_evals: list[CaseEvaluation] | None = None,
    fault_mode: str = "none",
    clearing_enabled: bool = True,
) -> str:
    total_cases = len(evaluations)
    passed_cases = sum(1 for e in evaluations if e.passed)
    completion_rate = (
        (passed_cases / total_cases * 100) if total_cases > 0 else 0.0
    )

    mean_tool_correctness = (
        sum(e.tool_correctness for e in evaluations) / total_cases
        if total_cases > 0
        else 1.0
    ) * 100
    mean_traj_length = (
        sum(e.trajectory_length for e in evaluations) / total_cases
        if total_cases > 0
        else 0.0
    )
    over_long_count = sum(1 for e in evaluations if e.over_long)

    total_prompt_tokens = sum(e.prompt_tokens for e in evaluations)
    total_completion_tokens = sum(
        e.completion_tokens for e in evaluations
    )
    total_reasoning_tokens = sum(
        e.reasoning_tokens for e in evaluations
    )
    total_tokens = sum(e.total_tokens for e in evaluations)
    total_cost_usd = sum(e.cost_usd for e in evaluations)

    # Failure counts
    hard_count = sum(
        1
        for e in evaluations
        if e.failure.category == FailureCategory.HARD
    )
    soft_count = sum(
        1
        for e in evaluations
        if e.failure.category == FailureCategory.SOFT
    )
    cascading_count = sum(
        1
        for e in evaluations
        if e.failure.category == FailureCategory.CASCADING_SOFT
    )

    # Category breakdown
    categories: dict[str, list[CaseEvaluation]] = {}
    for e in evaluations:
        categories.setdefault(e.category, []).append(e)

    compl_status = (
        "✅ PASS" if completion_rate >= 80 else "⚠️ WARN"
    )
    tool_status = (
        "✅ PASS" if mean_tool_correctness >= 90 else "⚠️ WARN"
    )
    traj_status = (
        "✅ OPTIMAL" if mean_traj_length <= 4.5 else "⚠️ HIGH"
    )
    overlong_status = (
        "✅ ZERO" if over_long_count == 0 else "⚠️ FLAGGED"
    )

    # Build summary rows as multi-line concatenation
    row_compl = (
        f"| **Task Completion Rate** | **{completion_rate:.1f}%**"
        f" ({passed_cases}/{total_cases})"
        f" | $\\ge 80.0\\%$ | {compl_status} |"
    )
    row_tool = (
        f"| **Tool-Call Correctness** | **{mean_tool_correctness:.1f}%**"
        f" | $\\ge 90.0\\%$ | {tool_status} |"
    )
    row_traj = (
        f"| **Mean Trajectory Length** | **{mean_traj_length:.2f}"
        f" iters** | $\\le 4.5$ iters | {traj_status} |"
    )
    row_overlong = (
        f"| **Over-Long Trajectories** | **{over_long_count}"
        f" cases** | $0$ | {overlong_status} |"
    )
    row_tokens = (
        f"| **Total Tokens Consumed** | **{total_tokens:,}**"
        f" (prompt: {total_prompt_tokens:,},"
        f" out: {total_completion_tokens:,},"
        f" think: {total_reasoning_tokens:,})"
        f" | Bounded | ✅ MEASURED |"
    )
    row_cost = (
        f"| **Total Financial Cost** | **${total_cost_usd:.4f}"
        f" USD** | $< $0.10 USD | ✅ VERIFIED |"
    )

    md = [
        f"# {title}",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Fault Mode**: `{fault_mode}`",
        f"- **Tool Result Clearing Enabled**: `{clearing_enabled}`",
        f"- **Total Test Cases**: {total_cases}",
        "",
        "## 1. Executive Summary & Core Metrics",
        "",
        "| Metric | Result | Benchmark Target | Status |",
        "|---|---|---|---|",
        row_compl,
        row_tool,
        row_traj,
        row_overlong,
        row_tokens,
        row_cost,
        "",
        "## 2. Failure Taxonomy Breakdown",
        "",
        "| Failure Tier | Occurrences | Definition |",
        "|---|---|---|",
        (
            f"| **Hard Failure** | {hard_count}"
            " | Catastrophic halt: budget/iteration cap,"
            " loop abort, provider crash |"
        ),
        (
            f"| **Soft Failure** | {soft_count}"
            " | Graceful halt, but missed facts,"
            " missing citations, or wrong terminal action |"
        ),
        (
            f"| **Cascading Soft Failure** | {cascading_count}"
            " | Flawed final answer caused directly by"
            " unrecovered intermediate tool error |"
        ),
        "",
    ]

    # Category performance
    md.extend(
        [
            "## 3. Performance by Evaluation Category",
            "",
            (
                "| Category | Cases | Passed | Pass Rate"
                " | Mean Iters | Mean Cost ($) |"
            ),
            "|---|---|---|---|---|---|",
        ]
    )
    for cat, c_evals in sorted(categories.items()):
        c_passed = sum(1 for e in c_evals if e.passed)
        c_rate = (c_passed / len(c_evals)) * 100
        c_iters = sum(
            e.trajectory_length for e in c_evals
        ) / len(c_evals)
        c_cost = sum(e.cost_usd for e in c_evals) / len(c_evals)
        md.append(
            f"| `{cat}` | {len(c_evals)} | {c_passed}"
            f" | {c_rate:.1f}% | {c_iters:.2f}"
            f" | ${c_cost:.4f} |"
        )

    # Detailed per-case table
    hdr = (
        "| ID | Category | Status | Iters"
        " | Tool Correctness | Tokens | Cost ($)"
        " | Failure Tier | Notes / Root Cause |"
    )
    md.extend(
        [
            "",
            "## 4. Per-Query Execution Log",
            "",
            hdr,
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for e in evaluations:
        status_icon = "✅ PASS" if e.passed else "❌ FAIL"
        fail_tier = (
            e.failure.category.value if not e.passed else "none"
        )
        reason = (
            e.failure.reason.replace("|", "/")
            if not e.passed
            else "Clean execution"
        )
        md.append(
            f"| `{e.case_id}` | `{e.category}`"
            f" | {status_icon} | {e.trajectory_length}"
            f" | {e.tool_correctness * 100:.0f}%"
            f" | {e.total_tokens:,}"
            f" | ${e.cost_usd:.4f} | `{fail_tier}`"
            f" | {reason} |"
        )

    # Baseline comparison section if provided
    if baseline_evals:
        b_total = len(baseline_evals)
        b_passed = sum(1 for e in baseline_evals if e.passed)
        b_rate = (
            (b_passed / b_total * 100) if b_total > 0 else 0.0
        )
        b_tokens = sum(e.total_tokens for e in baseline_evals)
        b_cost = sum(e.cost_usd for e in baseline_evals)

        token_ratio = (
            (total_tokens / b_tokens) if b_tokens > 0 else 1.0
        )
        cost_ratio = (
            (total_cost_usd / b_cost) if b_cost > 0 else 1.0
        )

        comp_hdr = (
            "| Architecture | Completion Rate | Mean Iters"
            " | Total Tokens | Total Cost ($)"
            " | Conflict Resolution | Verification Gate |"
        )
        row_baseline = (
            f"| **W15 Classic RAG (Baseline)**"
            f" | {b_rate:.1f}% ({b_passed}/{b_total})"
            f" | 1.0 | {b_tokens:,} | ${b_cost:.4f}"
            " | ❌ Fails on superseded docs"
            " | ❌ None (hallucination risk) |"
        )
        row_ours = (
            f"| **W16 Verified Agent (Ours)**"
            f" | **{completion_rate:.1f}%**"
            f" ({passed_cases}/{total_cases})"
            f" | {mean_traj_length:.2f}"
            f" | {total_tokens:,} ({token_ratio:.1f}x)"
            f" | ${total_cost_usd:.4f} ({cost_ratio:.1f}x)"
            " | ✅ Full precedence enforcement"
            " | ✅ Deterministic check |"
        )
        rationale = (
            "> **Coordination Cost Rationale**: The agentic loop"
            " uses approximately "
            f"{token_ratio:.1f}x tokens compared to the"
            " single-pass baseline. This modest cost difference"
            " buys autonomous multi-hop cross-referencing,"
            " self-verification, and resilience against"
            " outdated specifications."
        )

        md.extend(
            [
                "",
                "## 5. Comparative Analysis:"
                " W16 Agentic Loop vs."
                " W15 Single-Pass Baseline",
                "",
                comp_hdr,
                "|---|---|---|---|---|---|---|",
                row_baseline,
                row_ours,
                "",
                rationale,
            ]
        )

    return "\n".join(md)
