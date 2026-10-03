import json
import logging
import re
import time

from .cache import TTLCache
from .config import Settings
from .prompts import build_system_prompt
from .providers import AllProvidersFailedError, execute_chain
from .rag.retriever import Retriever
from .schemas import ASSISTANT_ANSWER_JSON_SCHEMA, AssistantAnswer, ChatRequest, ChatResponse
from .tools import TOOL_SPECS, ToolContext, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class Orchestrator:
    """Chat pipeline: cache -> RAG -> tool loop -> structured output, over the fallback chain."""

    def __init__(self, settings: Settings, providers: list, retriever: Retriever | None) -> None:
        self.settings = settings
        self.chain = providers
        self.retriever = retriever
        self.cache = TTLCache(settings.cache_ttl_s, settings.cache_max_items)

    @staticmethod
    def _parse_answer(content: str, had_context: bool) -> AssistantAnswer:
        text = _FENCE_RE.sub("", content.strip())
        try:
            return AssistantAnswer.model_validate_json(text)
        except Exception:
            pass
        match = _JSON_RE.search(text)
        if match:
            try:
                return AssistantAnswer.model_validate_json(match.group(0))
            except Exception:
                pass
        return AssistantAnswer(answer=content.strip(), used_context=had_context)

    @staticmethod
    def _degraded_answer(sources: list) -> str:
        if sources:
            top = "\n".join(f"- [{s.source}] {s.snippet[:160]}..." for s in sources[:3])
            return (
                "All language-model providers are currently unavailable. "
                "The closest passages retrieved from the knowledge base:\n" + top
            )
        return "All language-model providers are currently unavailable. Please retry shortly."

    async def chat(self, req: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        key = TTLCache.make_key(
            req.message, req.use_rag, req.use_tools, self.settings.temperature, self.settings.top_p
        )
        cached_response = self.cache.get(key)
        if cached_response is not None:
            cached_response.cached = True
            cached_response.latency_ms = int((time.perf_counter() - started) * 1000)
            return cached_response

        context, sources = "", []
        if req.use_rag and self.retriever is not None:
            try:
                context, sources = self.retriever.context_block(req.message)
            except Exception as exc:
                logger.warning("retrieval failed, continuing without RAG context: %s", exc)

        messages = [
            {"role": "system", "content": build_system_prompt(context)},
            {"role": "user", "content": req.message},
        ]
        gen_kwargs = {"tools": TOOL_SPECS} if req.use_tools else {}
        tools_called: list[str] = []

        degraded = False
        provider_used = "none"
        try:
            rounds = 0
            while True:
                provider_used, message = await execute_chain(
                    self.chain,
                    messages,
                    self.settings,
                    json_schema=ASSISTANT_ANSWER_JSON_SCHEMA,
                    **gen_kwargs,
                )
                if getattr(message, "tool_calls", None):
                    if rounds >= MAX_TOOL_ROUNDS:
                        parsed = AssistantAnswer(
                            answer="I hit the tool-round budget before reaching a final answer."
                        )
                        break
                    rounds += 1
                    messages.append(
                        {
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
                        }
                    )
                    for call in message.tool_calls:
                        try:
                            args = json.loads(call.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        result = execute_tool(
                            call.function.name, args, ToolContext(retriever=self.retriever)
                        )
                        tools_called.append(call.function.name)
                        logger.info("tool %s executed", call.function.name)
                        messages.append(
                            {"role": "tool", "tool_call_id": call.id, "content": result}
                        )
                    continue
                parsed = self._parse_answer(message.content or "", had_context=bool(sources))
                break
        except AllProvidersFailedError:
            degraded = True
            provider_used = "none"
            parsed = AssistantAnswer(
                answer=self._degraded_answer(sources), used_context=bool(sources)
            )

        response = ChatResponse(
            answer=parsed.answer.strip() or "(empty response)",
            provider_used=provider_used,
            degraded=degraded,
            cached=False,
            sources=sources,
            tools_called=tools_called,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if not degraded:
            self.cache.put(key, response)
        return response
