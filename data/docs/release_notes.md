# Release Notes & Changelog

## Version 2.1.0 — September 10, 2026

### Critical Configuration Updates (Supersedes v1.0.0 Architecture)
- **vLLM Context Length**: Bumped `--max-model-len` from `4096` to `8192` to accommodate longer system prompts and extended multi-turn tool calling traces. Note: older documentation (`vllm_local_serving.md` and `wk15_project.md`) referencing `4096` is now outdated.
- **Port Assignment**: Local vLLM internal port mapped to `8002` in multi-replica deployments, while default development compose remains `8001`.
- **Embedding Ingestion Batch Size**: Default batch upsert size for Qdrant was increased from `100` to `250` chunks per request to improve indexing throughput by 38%.

### Security & Resilience
- Circuit breaker trip threshold locked at `3` consecutive failures. Reset probe timeout standardized to `30.0` seconds.
- Minimum token bucket rate limit RPM set to `60` with burst capacity of `20`.
