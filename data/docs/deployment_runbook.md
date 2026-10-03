# Deployment & Operations Runbook

## Service Architecture Overview

The system consists of three interconnected services:
1. **API Backend**: FastAPI application exposing `/chat`, `/agent`, `/health`, and `/ingest`.
2. **Vector Store**: Qdrant running in embedded mode (`data/qdrant`) or standalone container on port `6333`.
3. **Local LLM Engine**: vLLM serving Qwen2.5-1.5B-Instruct on port `8001` (containerized CPU build).

## Resource Quotas & Limits

- **API Container**: Memory limit = 2.0 GiB, CPU quota = 2.0 cores.
- **vLLM Container**: Memory limit = 8.0 GiB (KV cache space configured to 4.0 GiB via `VLLM_CPU_KVCACHE_SPACE`).
- **Qdrant Storage**: Max collection vectors capped at 50,000 points.

## Health Probes & Triage

- Probe endpoint: `GET /health`
- Expected payload returns `status: "ok"`, `documents_indexed`, and per-provider breaker states (`closed`, `open`, `half-open`).
- If Gemini breaker is `open`, check API quota and transient rate limits. The circuit breaker resets automatically after `30.0` seconds.
