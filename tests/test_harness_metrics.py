from app.agent.trace import AgentResult, Step, TerminationReason, Trajectory, Usage
from eval.metrics import evaluate_case
from eval.taxonomy import FailureCategory


def test_evaluate_case_passes_on_correct_result():
    case = {
        "id": "test_01",
        "category": "single_hop",
        "query": "What is chunking?",
        "expected_terminal": "final_answer",
        "required_tools": ["search_knowledge_base"],
        "forbidden_tools": ["ask_user"],
        "required_sources": ["rag_basics.md"],
        "must_include_any": [["chunking", "chunks"]],
        "must_not_include": ["fabricated"],
        "max_reasonable_steps": 3,
    }

    traj = Trajectory(query="What is chunking?")
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={"query": "chunking"},
            result="chunking is splitting docs",
            sources=["rag_basics.md"],
            kind="evidence",
            ok=True,
        )
    )

    result = AgentResult(
        answer="Chunking is splitting documents into smaller chunks.",
        status="answered",
        termination_reason=TerminationReason.ANSWERED,
        iterations=2,
        trajectory=traj,
        usage=Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        citations=["rag_basics.md"],
        confidence="high",
        evidence_sufficient=True,
        provider_used="gemini",
    )

    eval_res = evaluate_case(case, result)
    assert eval_res.passed is True
    assert eval_res.failure.category == FailureCategory.NONE
    assert eval_res.cost_usd > 0.0


def test_evaluate_case_detects_cascading_soft_failure():
    case = {
        "id": "test_02",
        "category": "numeric",
        "query": "Calculate rate",
        "expected_terminal": "final_answer",
        "required_tools": ["search_knowledge_base", "calculator"],
        "required_sources": ["rates.md"],
        "must_include_any": [["42"]],
        "max_reasonable_steps": 4,
    }

    traj = Trajectory(query="Calculate rate")
    # Step 1 failed
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={"query": "rates"},
            result="error: tool unavailable",
            sources=[],
            kind="evidence",
            ok=False,
            error="tool_unavailable",
        )
    )

    result = AgentResult(
        answer="The answer is something else.",
        status="answered",
        termination_reason=TerminationReason.ANSWERED,
        iterations=2,
        trajectory=traj,
        usage=Usage(),
        citations=[],
        confidence="low",
        evidence_sufficient=False,
        provider_used="gemini",
    )

    eval_res = evaluate_case(case, result)
    assert eval_res.passed is False
    assert eval_res.failure.category == FailureCategory.CASCADING_SOFT
    assert eval_res.failure.root_cause_step == 1
