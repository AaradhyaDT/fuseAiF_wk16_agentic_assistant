"""CLI Evaluation Harness built from scratch for W16 Agentic Assistant."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from app.agent.loop import AgentLoop
from app.agent.trace import AgentResult, Step, Trajectory, Usage
from app.config import get_settings
from app.orchestrator import Orchestrator
from app.providers import build_providers
from app.rag.embeddings import SentenceTransformerEmbedder
from app.rag.retriever import Retriever
from app.rag.store import VectorStore
from app.schemas import ChatRequest

from .metrics import CaseEvaluation, evaluate_case
from .report import generate_markdown_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eval.harness")


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                cases.append(json.loads(line))
    return cases


async def run_baseline_case(orchestrator: Orchestrator, case: dict[str, Any]) -> AgentResult:
    """Run a test query through the W15 single-pass RAG pipeline."""
    started = time.perf_counter()
    req = ChatRequest(message=case["query"], use_rag=True, use_tools=True)
    resp = await orchestrator.chat(req)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # Estimate single-pass token consumption
    prompt_chars = len(case["query"]) + sum(len(s.snippet) for s in resp.sources) + 800
    comp_chars = len(resp.answer)
    usage = Usage(
        prompt_tokens=prompt_chars // 4,
        completion_tokens=comp_chars // 4,
        total_tokens=(prompt_chars + comp_chars) // 4,
        llm_calls=1 + len(resp.tools_called),
        estimated=True,
    )

    traj = Trajectory(query=case["query"])
    for i, tool_name in enumerate(resp.tools_called, 1):
        traj.add(Step(step=i, iteration=1, tool=tool_name, args={}, result="executed", kind="tool"))

    citations = [s.source for s in resp.sources]
    return AgentResult(
        answer=resp.answer,
        status="answered",
        termination_reason=resp.provider_used,
        iterations=1,
        trajectory=traj,
        usage=usage,
        citations=citations,
        confidence="medium",
        evidence_sufficient=bool(resp.sources),
        provider_used=resp.provider_used,
        latency_ms=latency_ms,
    )


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="W16 Agentic AI Evaluation Harness")
    parser.add_argument(
        "--cases", default="eval/cases.jsonl", help="Path to golden test cases JSONL"
    )
    parser.add_argument("--provider-order", default="gemini", help="Provider fallback order")
    parser.add_argument(
        "--fault",
        default="none",
        choices=["none", "tool_unavailable", "malformed_retrieval", "timeout"],
    )
    parser.add_argument(
        "--no-clearing", action="store_true", help="Disable tool-result clearing (context ablation)"
    )
    parser.add_argument(
        "--baseline", action="store_true", help="Also evaluate against W15 classic baseline"
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of test queries")
    parser.add_argument(
        "--output-dir", default="eval/results", help="Directory for output artifacts"
    )
    args = parser.parse_args()

    settings = get_settings()
    settings.provider_order = args.provider_order

    cases_path = Path(args.cases)
    if not cases_path.exists():
        logger.error("Cases file not found: %s", cases_path)
        return 1

    cases = load_cases(cases_path)
    if args.limit:
        cases = cases[: args.limit]

    logger.info("Initializing vector store and retriever for evaluation...")
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    store = VectorStore(
        settings.collection_name,
        embedder,
        path=settings.qdrant_path,
        url=settings.qdrant_url or None,
    )
    retriever = Retriever(store, top_k=settings.top_k)
    providers = build_providers(settings)

    if not providers:
        logger.error("No active LLM providers configured! Check GEMINI_API_KEY or local endpoints.")
        return 1

    clearing_enabled = not args.no_clearing
    fault_mode = None if args.fault == "none" else args.fault

    agent_loop = AgentLoop(settings, providers, retriever, fault_mode=fault_mode)
    orchestrator = Orchestrator(settings, providers, retriever) if args.baseline else None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"eval_{args.fault}_{'cleared' if clearing_enabled else 'uncleared'}_{timestamp}"
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting evaluation run '%s' across %d queries...", run_id, len(cases))
    agent_evaluations: list[CaseEvaluation] = []
    baseline_evaluations: list[CaseEvaluation] = []
    trajectories_out: list[dict[str, Any]] = []

    for i, case in enumerate(cases, 1):
        cid = case["id"]
        logger.info(
            "[%d/%d] Running Case '%s' (%s): %s",
            i,
            len(cases),
            cid,
            case["category"],
            case["query"][:60],
        )

        # Execute agentic loop
        try:
            res = await agent_loop.run(
                case["query"],
                override_enable_clearing=clearing_enabled,
            )
        except Exception as exc:
            logger.error("Unhandled exception running agent loop on %s: %s", cid, exc)
            res = AgentResult(
                answer=f"Fatal exception: {exc}",
                status="failed",
                termination_reason="error",
                iterations=0,
                trajectory=Trajectory(query=case["query"]),
                usage=Usage(),
                provider_used="none",
            )

        c_eval = evaluate_case(case, res)
        agent_evaluations.append(c_eval)
        trajectories_out.append(
            {
                "case_id": cid,
                "category": case["category"],
                "passed": c_eval.passed,
                "result": res.to_dict(),
            }
        )

        logger.info(
            "   -> %s (iters=%d, tools=%s, cost=$%.4f, failure=%s)",
            "✅ PASS" if c_eval.passed else "❌ FAIL",
            c_eval.trajectory_length,
            round(c_eval.tool_correctness, 2),
            c_eval.cost_usd,
            c_eval.failure.category.value,
        )

        # Execute baseline if requested
        if orchestrator is not None:
            b_res = await run_baseline_case(orchestrator, case)
            b_eval = evaluate_case(case, b_res)
            baseline_evaluations.append(b_eval)

        # Reset circuit breakers so one failure doesn't cascade
        for p in providers:
            p.breaker.state = "closed"
            p.breaker._failures = 0
            p.breaker._opened_at = None

        # Rate limit cushion — Gemini free tier allows 5 RPM
        await asyncio.sleep(15.0)

    # Compile and save reports
    md_report = generate_markdown_report(
        agent_evaluations,
        run_id=run_id,
        baseline_evals=baseline_evaluations if args.baseline else None,
        fault_mode=args.fault,
        clearing_enabled=clearing_enabled,
    )

    (out_dir / "report.md").write_text(md_report, encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps([e.to_dict() for e in agent_evaluations], indent=2), encoding="utf-8"
    )
    with open(out_dir / "trajectories.jsonl", "w", encoding="utf-8") as f:
        for t in trajectories_out:
            f.write(json.dumps(t) + "\n")

    # If this is a standard clean run, also update root canonical report
    if args.fault == "none" and clearing_enabled:
        canonical_file = Path(args.output_dir) / "REPORT.md"
        canonical_file.parent.mkdir(parents=True, exist_ok=True)
        canonical_file.write_text(md_report, encoding="utf-8")
        logger.info("Updated canonical report at %s", canonical_file)

    logger.info("Evaluation complete! Artifacts written to %s", out_dir)
    summary = md_report[:1200]
    trailer = (
        "\n...\n[Full report saved to "
        + str(out_dir / "report.md") + "]"
    )
    # Safe print: Windows console may not support emoji
    try:
        print("\n" + "=" * 70)
        print(summary + trailer)
        print("=" * 70 + "\n")
    except UnicodeEncodeError:
        safe = (summary + trailer).encode(
            "ascii", errors="replace"
        ).decode("ascii")
        print("\n" + "=" * 70)
        print(safe)
        print("=" * 70 + "\n")

    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
