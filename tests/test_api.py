import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.resilience import CircuitBreaker
from tests.conftest import BagOfWordsEmbedder


class _Message:
    content = json.dumps({"answer": "stub says hi", "used_context": False})
    tool_calls = None


class StubProvider:
    name = "stub"

    def __init__(self):
        self.breaker = CircuitBreaker("stub")

    async def complete(self, messages, **kwargs):
        return _Message()


def make_client(tmp_path, **overrides):
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        qdrant_path=str(tmp_path / "qdrant"),
        data_docs_dir=str(tmp_path / "docs"),
        **overrides,
    )
    app = create_app(settings, embedding_fn=BagOfWordsEmbedder())
    app.state.orchestrator.chain = [StubProvider()]
    return TestClient(app)


def test_health_reports_providers_and_doc_count(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["providers"][0]["name"] == "stub"
    assert body["documents_indexed"] == 0


def test_chat_returns_structured_response(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "stub says hi"
    assert body["provider_used"] == "stub"
    assert body["cached"] is False
    assert body["degraded"] is False


def test_chat_second_identical_call_is_cached(tmp_path):
    client = make_client(tmp_path)
    client.post("/chat", json={"message": "hello"})
    body = client.post("/chat", json={"message": "hello"}).json()
    assert body["cached"] is True


def test_rate_limit_returns_429_when_exhausted(tmp_path):
    client = make_client(tmp_path, rate_limit_rpm=60, rate_limit_burst=2)
    codes = [client.post("/chat", json={"message": "m"}).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert 429 in codes


def test_ingest_endpoint_indexes_documents(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "notes.md").write_text("zebra crossing rules\n\nslow down near schools")
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        data_docs_dir=str(docs_dir),
        qdrant_path=str(tmp_path / "db"),
    )
    app = create_app(settings, embedding_fn=BagOfWordsEmbedder())
    app.state.orchestrator.chain = [StubProvider()]
    client = TestClient(app)
    stats = client.post("/ingest").json()
    assert stats["files"] == 1
    assert stats["chunks"] >= 1
    health = client.get("/health").json()
    assert health["documents_indexed"] == stats["chunks"]


def test_chat_degrades_gracefully_when_all_providers_down(tmp_path):
    class BrokenProvider:
        name = "broken"

        def __init__(self):
            self.breaker = CircuitBreaker("broken", failure_threshold=100)

        async def complete(self, messages, **kwargs):
            raise RuntimeError("outage")

    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        retry_attempts=1,
        retry_backoff_s=0.001,
        qdrant_path=str(tmp_path / "qdrant"),
    )
    app = create_app(settings, embedding_fn=BagOfWordsEmbedder())
    app.state.orchestrator.chain = [BrokenProvider()]
    client = TestClient(app)
    body = client.post("/chat", json={"message": "hi"}).json()
    assert body["provider_used"] == "none"
    assert body["degraded"] is True
    assert "unavailable" in body["answer"]


def test_agent_endpoint_returns_structured_response(tmp_path):
    class AgentStubProvider:
        name = "agent_stub"

        def __init__(self):
            self.breaker = CircuitBreaker("agent_stub")

        async def complete_raw(self, messages, **kwargs):
            class _Call:
                id = "call_1"
                function = type(
                    "Fn",
                    (),
                    {
                        "name": "final_answer",
                        "arguments": json.dumps(
                            {
                                "answer": "Agent answer.",
                                "citations": [],
                                "confidence": "high",
                                "evidence_sufficient": False,
                                "rationale": "done",
                            }
                        ),
                    },
                )()

                def model_dump(self):
                    return {
                        "id": self.id,
                        "type": "function",
                        "function": {
                            "name": self.function.name,
                            "arguments": self.function.arguments,
                        },
                    }

            msg = type("Msg", (), {"content": None, "tool_calls": [_Call()]})()
            usage = {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
            return msg, usage

    settings = Settings(_env_file=None, gemini_api_key="", qdrant_path=str(tmp_path / "qdrant"))
    app = create_app(settings, embedding_fn=BagOfWordsEmbedder())
    app.state.agent_loop.providers = [AgentStubProvider()]
    client = TestClient(app)

    resp = client.post("/agent", json={"message": "hello agent"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Agent answer."
    assert body["status"] == "answered"
    assert body["termination_reason"] == "answered"
    assert body["iterations"] == 1
    assert "trajectory" in body
    assert body["usage"]["total_tokens"] == 70
