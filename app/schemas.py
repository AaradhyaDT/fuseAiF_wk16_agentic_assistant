from pydantic import BaseModel, Field


class Source(BaseModel):
    source: str
    snippet: str
    score: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None
    use_rag: bool = True
    use_tools: bool = True


class AssistantAnswer(BaseModel):
    """Structured payload every provider is asked to emit."""

    answer: str
    used_context: bool = False


ASSISTANT_ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "used_context": {"type": "boolean"},
    },
    "required": ["answer"],
}


class ChatResponse(BaseModel):
    answer: str
    provider_used: str
    degraded: bool = False
    cached: bool = False
    sources: list[Source] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    latency_ms: int = 0


class HistoryMessage(BaseModel):
    role: str
    content: str


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[HistoryMessage] = Field(default_factory=list)
    enable_clearing: bool | None = None
    fault_mode: str | None = None


class AgentResponse(BaseModel):
    answer: str
    status: str  # answered | needs_clarification | unverified | failed
    termination_reason: str
    iterations: int
    citations: list[str] = Field(default_factory=list)
    confidence: str = "low"
    evidence_sufficient: bool = False
    provider_used: str = "none"
    verification_failures: list[str] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    trajectory: dict = Field(default_factory=dict)
    latency_ms: int = 0
