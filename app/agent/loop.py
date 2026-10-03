"""Core autonomous agentic loop implementing Verified Answering.

Runs an iterative ReAct-style loop with:
- Structured trace tracking (Step, Trajectory, Usage)
- Multi-technique context engineering (Tool clearing, Notes scratchpad, Skills index)
- Deterministic self-check verification gate for final_answer
- Strict bounding guards (iteration limit, token budget, repeat-call detection, timeout)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..providers import AllProvidersFailedError, execute_chain
from .context import NotesStore, SkillRegistry, ToolRound, make_stub, render_transcript
from .faults import FaultInjector
from .tools import AGENT_TOOL_SPECS, AgentToolbox
from .trace import (
    AgentResult,
    LLMCall,
    Step,
    TerminationReason,
    Trajectory,
    Usage,
)
from .verifier import normalise_citations, verify_final

logger = logging.getLogger(__name__)


class RepeatCallDetector:
    """Detects cycles where the agent calls the exact same tool with the exact same args."""

    def __init__(self, max_identical_repeats: int = 2) -> None:
        self.max_repeats = max_identical_repeats
        self._counts: dict[str, int] = {}
        self._last_sig: str | None = None
        self._consecutive: int = 0

    def record(self, tool: str, args: dict[str, Any]) -> bool:
        """Returns True if a runaway loop is detected."""
        # Normalize args by stripping rationale
        clean_args = {k: v for k, v in args.items() if k != "rationale"}
        sig = f"{tool}:{json.dumps(clean_args, sort_keys=True)}"
        self._counts[sig] = self._counts.get(sig, 0) + 1

        if sig == self._last_sig:
            self._consecutive += 1
        else:
            self._consecutive = 1
        self._last_sig = sig

        if self._consecutive >= self.max_repeats or self._counts[sig] >= (self.max_repeats + 1):
            return True
        return False


class AgentLoop:
    """Autonomous agent loop coordinator."""

    def __init__(
        self,
        settings: Settings,
        providers: list[Any],
        retriever: Any,
        *,
        fault_mode: str | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.retriever = retriever
        self.fault_mode = fault_mode or settings.agent_fault_mode

        self.skills = SkillRegistry(Path(settings.skills_dir))
        self.prompt_template = self._load_prompt(settings.agent_prompt_version)

    def _load_prompt(self, version: str) -> str:
        prompt_path = Path(__file__).parent / "prompts" / f"agent_{version}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        # Fallback to default v1
        default_path = Path(__file__).parent / "prompts" / "agent_v1.md"
        if default_path.exists():
            return default_path.read_text(encoding="utf-8")
        return "You are a helpful assistant. Use tools to verify your answers."

    def _build_system_prompt(self, notes: NotesStore) -> str:
        return self.prompt_template.format(
            skills_index=self.skills.index(),
            notes=notes.render(),
        )

    async def run(
        self,
        query: str,
        *,
        history: list[dict[str, str]] | None = None,
        override_enable_clearing: bool | None = None,
    ) -> AgentResult:
        started_at = time.perf_counter()
        trajectory = Trajectory(query=query)
        usage = Usage()
        notes = NotesStore(max_chars=self.settings.agent_notes_max_chars)
        detector = RepeatCallDetector(max_identical_repeats=2)

        toolbox = AgentToolbox(
            retriever=self.retriever,
            docs_dir=self.settings.data_docs_dir,
            notes=notes,
            skills=self.skills,
            retrieval_k=self.settings.agent_retrieval_k,
            min_relevance=self.settings.agent_min_relevance,
            snippet_chars=self.settings.agent_snippet_chars,
        )
        if self.fault_mode:
            executor: Any = FaultInjector(
                toolbox, self.fault_mode, timeout_s=self.settings.agent_tool_timeout_s
            )
        else:
            executor = toolbox

        enable_clearing = (
            override_enable_clearing
            if override_enable_clearing is not None
            else self.settings.agent_enable_clearing
        )

        rounds: list[ToolRound] = []
        verification_attempts = 0
        all_verification_failures: list[str] = []
        raw_text_nudges = 0
        provider_used = "none"

        # Initialize base conversation messages
        user_turn: list[dict[str, Any]] = []
        if history:
            for item in history:
                user_turn.append(
                    {"role": item.get("role", "user"), "content": item.get("content", "")}
                )
        user_turn.append({"role": "user", "content": query})

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            # Check token budget
            if usage.total_tokens >= self.settings.agent_max_total_tokens:
                logger.warning(
                    "Agent token budget exhausted: %d >= %d",
                    usage.total_tokens,
                    self.settings.agent_max_total_tokens,
                )
                return AgentResult(
                    answer="Execution halted: token budget exceeded.",
                    status="failed",
                    termination_reason=TerminationReason.BUDGET_EXHAUSTED,
                    iterations=iteration,
                    trajectory=trajectory,
                    usage=usage,
                    provider_used=provider_used,
                    notes=notes.to_list(),
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )

            # Rebuild messages with context engineering
            system_msg = {"role": "system", "content": self._build_system_prompt(notes)}
            transcript_msgs, _ = render_transcript(
                rounds,
                enable_clearing=enable_clearing,
                keep_last=self.settings.agent_keep_last_tool_rounds,
            )
            messages = [system_msg, *user_turn, *transcript_msgs]

            llm_call_start = time.perf_counter()
            try:
                provider_used, message, call_usage = await execute_chain(
                    self.providers,
                    messages,
                    self.settings,
                    with_usage=True,
                    tools=AGENT_TOOL_SPECS,
                )
            except AllProvidersFailedError as exc:
                logger.error("All providers failed during agent loop: %s", exc)
                return AgentResult(
                    answer="All LLM providers are currently unavailable. Execution halted.",
                    status="failed",
                    termination_reason=TerminationReason.PROVIDER_FAILURE,
                    iterations=iteration,
                    trajectory=trajectory,
                    usage=usage,
                    provider_used="none",
                    notes=notes.to_list(),
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )

            call_latency = int((time.perf_counter() - llm_call_start) * 1000)
            usage.add(call_usage)
            trajectory.llm_calls.append(
                LLMCall(
                    iteration=iteration,
                    provider=provider_used,
                    usage=call_usage,
                    prompt_chars=sum(len(str(m.get("content") or "")) for m in messages),
                    latency_ms=call_latency,
                )
            )

            # Handle case where model returned prose instead of calling tools
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                content = str(getattr(message, "content", "") or "").strip()
                if raw_text_nudges == 0 and iteration < self.settings.agent_max_iterations:
                    raw_text_nudges += 1
                    # Synthesize assistant message and user nudge to invoke tool
                    nudge_text = (
                        "Notice: Please invoke 'final_answer' to submit your answer with "
                        "citations, or 'ask_user' if clarification is needed."
                    )
                    current_round = ToolRound(
                        assistant={"role": "assistant", "content": content},
                        tool_messages=[{"role": "user", "content": nudge_text}],
                        stubs=["[cleared] System nudge to call final_answer"],
                    )
                    rounds.append(current_round)
                    continue

                # Fallback: treat text as unverified final answer
                return AgentResult(
                    answer=content or "(empty response)",
                    status="unverified",
                    termination_reason=TerminationReason.ANSWERED_UNVERIFIED,
                    iterations=iteration,
                    trajectory=trajectory,
                    usage=usage,
                    provider_used=provider_used,
                    notes=notes.to_list(),
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                )

            # Process tool calls in this turn
            assistant_turn = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            }
            round_tool_messages: list[dict[str, Any]] = []
            round_stubs: list[str] = []

            for tc in tool_calls[: self.settings.agent_max_tool_calls_per_iter]:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    fn_args = {}

                step_idx = trajectory.next_index()
                rationale = str(fn_args.get("rationale", "")).strip()

                # Loop detection guard
                if detector.record(fn_name, fn_args):
                    logger.warning("Runaway tool loop detected for %s: %s", fn_name, fn_args)
                    step = Step(
                        step=step_idx,
                        iteration=iteration,
                        tool=fn_name,
                        args=fn_args,
                        result="Execution aborted: repetitive tool invocation loop detected.",
                        reasoning=rationale,
                        ok=False,
                        error="loop_detected",
                        kind="guard",
                    )
                    trajectory.add(step)
                    return AgentResult(
                        answer="Execution halted: repetitive loop detected.",
                        status="failed",
                        termination_reason=TerminationReason.LOOP_DETECTED,
                        iterations=iteration,
                        trajectory=trajectory,
                        usage=usage,
                        provider_used=provider_used,
                        notes=notes.to_list(),
                        latency_ms=int((time.perf_counter() - started_at) * 1000),
                    )

                # 1. Terminal Tool: ask_user
                if fn_name == "ask_user":
                    question = str(fn_args.get("question", "")).strip()
                    step = Step(
                        step=step_idx,
                        iteration=iteration,
                        tool=fn_name,
                        args=fn_args,
                        result=f"Clarification asked: {question}",
                        reasoning=rationale,
                        ok=True,
                        kind="terminal",
                    )
                    trajectory.add(step)
                    return AgentResult(
                        answer=question,
                        status="needs_clarification",
                        termination_reason=TerminationReason.ASKED_USER,
                        iterations=iteration,
                        trajectory=trajectory,
                        usage=usage,
                        provider_used=provider_used,
                        notes=notes.to_list(),
                        latency_ms=int((time.perf_counter() - started_at) * 1000),
                    )

                # 2. Terminal Tool: final_answer
                if fn_name == "final_answer":
                    answer = str(fn_args.get("answer", "")).strip()
                    confidence = str(fn_args.get("confidence", "low"))
                    evidence_sufficient = bool(fn_args.get("evidence_sufficient", False))
                    raw_citations = fn_args.get("citations", [])
                    citations = normalise_citations(raw_citations)

                    # Deterministic Verification Gate
                    verif_problems = verify_final(fn_args, trajectory)
                    if verif_problems:
                        verification_attempts += 1
                        all_verification_failures.extend(verif_problems)
                        logger.info(
                            "Verification gate failed on attempt %d: %s",
                            verification_attempts,
                            verif_problems,
                        )

                        if verification_attempts <= self.settings.agent_max_verification_retries:
                            verif_msg = (
                                f"VERIFICATION FAILED: {'; '.join(verif_problems)}. "
                                "You must retrieve cited docs with search/read, "
                                "or remove unverified citations with evidence_sufficient=false."
                            )
                            step = Step(
                                step=step_idx,
                                iteration=iteration,
                                tool=fn_name,
                                args=fn_args,
                                result=verif_msg,
                                reasoning=rationale,
                                ok=False,
                                error="verification_failed",
                                kind="terminal",
                            )
                            trajectory.add(step)
                            round_tool_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": verif_msg,
                                }
                            )
                            round_stubs.append(
                                f"[cleared] verif failed ({len(verif_problems)} problems)"
                            )
                            continue

                        # Retries exhausted: accept as unverified
                        step = Step(
                            step=step_idx,
                            iteration=iteration,
                            tool=fn_name,
                            args=fn_args,
                            result=f"Accepted unverified: {'; '.join(verif_problems)}",
                            reasoning=rationale,
                            ok=False,
                            error="verification_exhausted",
                            kind="terminal",
                        )
                        trajectory.add(step)
                        return AgentResult(
                            answer=answer,
                            status="unverified",
                            termination_reason=TerminationReason.ANSWERED_UNVERIFIED,
                            iterations=iteration,
                            trajectory=trajectory,
                            usage=usage,
                            citations=citations,
                            confidence=confidence,
                            evidence_sufficient=evidence_sufficient,
                            provider_used=provider_used,
                            verification_failures=all_verification_failures,
                            notes=notes.to_list(),
                            latency_ms=int((time.perf_counter() - started_at) * 1000),
                        )

                    # Verification Passed!
                    step = Step(
                        step=step_idx,
                        iteration=iteration,
                        tool=fn_name,
                        args=fn_args,
                        result="Verification passed.",
                        reasoning=rationale,
                        ok=True,
                        kind="terminal",
                    )
                    trajectory.add(step)
                    return AgentResult(
                        answer=answer,
                        status="answered",
                        termination_reason=TerminationReason.ANSWERED,
                        iterations=iteration,
                        trajectory=trajectory,
                        usage=usage,
                        citations=citations,
                        confidence=confidence,
                        evidence_sufficient=evidence_sufficient,
                        provider_used=provider_used,
                        verification_failures=all_verification_failures,
                        notes=notes.to_list(),
                        latency_ms=int((time.perf_counter() - started_at) * 1000),
                    )

                # 3. Non-Terminal Tool Execution
                t_start = time.perf_counter()
                try:
                    # Run sync tool inside asyncio with timeout
                    outcome = await asyncio.wait_for(
                        asyncio.to_thread(executor.run, fn_name, fn_args, step=step_idx),
                        timeout=self.settings.agent_tool_timeout_s,
                    )
                except TimeoutError:
                    from .tools import ToolOutcome

                    t_out = self.settings.agent_tool_timeout_s
                    outcome = ToolOutcome(
                        result=f"error: tool '{fn_name}' timed out after {t_out}s",
                        ok=False,
                        error="timeout",
                        kind="evidence"
                        if fn_name in {"search_knowledge_base", "read_document"}
                        else "tool",
                    )
                except Exception as exc:
                    from .tools import ToolOutcome

                    outcome = ToolOutcome(
                        result=f"error: {type(exc).__name__}: {exc}",
                        ok=False,
                        error="exception",
                        kind="evidence"
                        if fn_name in {"search_knowledge_base", "read_document"}
                        else "tool",
                    )

                t_dur = int((time.perf_counter() - t_start) * 1000)
                step = Step(
                    step=step_idx,
                    iteration=iteration,
                    tool=fn_name,
                    args=fn_args,
                    result=outcome.result,
                    reasoning=rationale,
                    ok=outcome.ok,
                    error=outcome.error,
                    kind=outcome.kind,
                    sources=outcome.sources,
                    latency_ms=t_dur,
                )
                trajectory.add(step)

                round_tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": outcome.result,
                    }
                )
                stub = make_stub(fn_name, fn_args, outcome.result, outcome.sources)
                round_stubs.append(stub)

            rounds.append(
                ToolRound(
                    assistant=assistant_turn, tool_messages=round_tool_messages, stubs=round_stubs
                )
            )

        # Iteration cap reached without final answer
        logger.warning(
            "Agent reached max iterations (%d) without terminal action",
            self.settings.agent_max_iterations,
        )
        return AgentResult(
            answer="Execution halted: reached maximum iteration limit before final answer.",
            status="failed",
            termination_reason=TerminationReason.MAX_ITERATIONS,
            iterations=self.settings.agent_max_iterations,
            trajectory=trajectory,
            usage=usage,
            provider_used=provider_used,
            notes=notes.to_list(),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )
