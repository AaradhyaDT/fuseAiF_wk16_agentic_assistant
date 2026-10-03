# Provider Pricing & Cost Model (2026 Rate Card)

Official per-token and compute rates for all LLM and embedding providers supported by the AI Fellowship assistant stack.

## Cloud API Providers

### Google Gemini 2.5 Flash
- **Input Tokens**: $0.1500 per 1,000,000 tokens ($0.00000015 per token)
- **Output Tokens**: $0.6000 per 1,000,000 tokens ($0.00000060 per token)
- **Thinking / Reasoning Tokens**: Billed as output tokens at $0.6000 per 1,000,000 tokens
- **Context Caching**: $0.0375 per 1,000,000 tokens cached per hour

## Self-Hosted & Local Providers

### vLLM CPU Instance (AWS c6i.2xlarge Cloud Hosting)
- **Hourly Cost**: $0.3400 per hour
- **Effective Inference Cost**: Sized for continuous baseline loads. At an average generation throughput of 25.0 tokens/second, 1,000,000 output tokens consume approximately 11.11 hours of compute, yielding an amortized cost of $3.778 per 1M output tokens.
- **Standby Idle Cost**: $0.3400 per hour regardless of query load.

### Ollama (Developer Local Machine)
- **Marginal Token Cost**: $0.0000 (runs on local CPU/iGPU hardware)
- **Power Consumption**: Negligible (<45W under peak inference)

## Embedding Services

### all-MiniLM-L6-v2 (Local Sentence-Transformers)
- **Inference Cost**: $0.0000 (runs in-memory within the FastAPI application container)
- **Memory Footprint**: ~240 MB RAM
