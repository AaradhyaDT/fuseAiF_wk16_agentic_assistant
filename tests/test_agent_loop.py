import json

import pytest

from app.agent.loop import AgentLoop, RepeatCallDetector
from app.agent.trace import TerminationReason
from app.config import Settings
from app.resilience import CircuitBreaker


class _ToolCall:
    def __init__(self, call_id: str, name: str, args: dict):
        self.id = call_id
        self.function = type("Fn", (), {"name": name, "arguments": json.dumps(args)})()

    def model_dump(self):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class _Message:
    def __init__(self, content: str | None = None, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class ScriptedProvider:
    name = "scripted"

    def __init__(self, script: list[_Message]):
        self.breaker = CircuitBreaker("scripted")
        self.script = list(script)
        self.call_count = 0

    async def complete_raw(self, messages, **kwargs):
        self.call_count += 1
        if self.script:
            msg = self.script.pop(0)
        else:
            msg = _Message(content="Out of script messages")
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "reasoning_tokens": 0,
            "total_tokens": 150,
        }
        return msg, usage


def test_repeat_call_detector():
    detector = RepeatCallDetector(max_identical_repeats=2)
    assert detector.record("search_knowledge_base", {"query": "q1", "rationale": "first"}) is False
    assert detector.record("search_knowledge_base", {"query": "q1", "rationale": "second"}) is True


@pytest.mark.asyncio
async def test_agent_loop_runs_multiple_iterations_and_answers(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "release_notes.md").write_text("v2.1.0: vLLM context length is 8192.")

    script = [
        # Turn 1: Call search_knowledge_base
        _Message(
            tool_calls=[
                _ToolCall(
                    "c1",
                    "search_knowledge_base",
                    {"query": "vLLM context length", "rationale": "look up release notes"},
                )
            ]
        ),
        # Turn 2: Call final_answer with retrieved citation
        _Message(
            tool_calls=[
                _ToolCall(
                    "c2",
                    "final_answer",
                    {
                        "answer": "The context length is 8192.",
                        "citations": ["release_notes.md"],
                        "confidence": "high",
                        "evidence_sufficient": True,
                        "rationale": "submit answer",
                    },
                )
            ]
        ),
    ]

    provider = ScriptedProvider(script)
    settings = Settings(
        _env_file=None,
        data_docs_dir=str(docs_dir),
        qdrant_path=str(tmp_path / "qdrant"),
        skills_dir=str(tmp_path / "skills"),
        agent_max_iterations=5,
    )

    class FakeRetriever:
        def retrieve(self, query, k=4):
            return [
                {
                    "source": "release_notes.md",
                    "text": "vLLM context length is 8192.",
                    "distance": 0.1,
                }
            ]

    loop = AgentLoop(settings, [provider], FakeRetriever())
    result = await loop.run("What is the vLLM context length?")

    assert result.status == "answered"
    assert result.termination_reason == TerminationReason.ANSWERED
    assert result.iterations == 2
    assert "8192" in result.answer
    assert "release_notes.md" in result.citations
    assert len(result.trajectory.steps) == 2


@pytest.mark.asyncio
async def test_agent_loop_stops_on_max_iterations(tmp_path):
    # Endless search script
    script = [
        _Message(
            tool_calls=[
                _ToolCall(
                    f"c{i}",
                    "search_knowledge_base",
                    {"query": f"query {i}", "rationale": f"step {i}"},
                )
            ]
        )
        for i in range(10)
    ]
    provider = ScriptedProvider(script)
    settings = Settings(
        _env_file=None,
        data_docs_dir=str(tmp_path),
        qdrant_path=str(tmp_path),
        agent_max_iterations=3,
    )

    class FakeRetriever:
        def retrieve(self, query, k=4):
            return []

    loop = AgentLoop(settings, [provider], FakeRetriever())
    result = await loop.run("Indefinite search query")

    assert result.status == "failed"
    assert result.termination_reason == TerminationReason.MAX_ITERATIONS
    assert result.iterations == 3


@pytest.mark.asyncio
async def test_agent_loop_handles_ask_user(tmp_path):
    script = [
        _Message(
            tool_calls=[
                _ToolCall(
                    "c1",
                    "ask_user",
                    {"question": "Which environment do you mean?", "rationale": "ambiguous prompt"},
                )
            ]
        )
    ]
    provider = ScriptedProvider(script)
    settings = Settings(_env_file=None, data_docs_dir=str(tmp_path), qdrant_path=str(tmp_path))

    loop = AgentLoop(settings, [provider], None)
    result = await loop.run("Deploy the application.")

    assert result.status == "needs_clarification"
    assert result.termination_reason == TerminationReason.ASKED_USER
    assert "Which environment" in result.answer
