"""Token pricing catalog for accurate cost accounting across evaluation runs."""

# Rates per 1,000,000 tokens (USD)
RATES_PER_MILLION = {
    "gemini": {
        "prompt": 0.1500,
        "completion": 0.6000,
        "reasoning": 0.6000,
    },
    "gemini-2.5-flash": {
        "prompt": 0.1500,
        "completion": 0.6000,
        "reasoning": 0.6000,
    },
    "vllm": {
        "prompt": 0.0000,  # Billed as compute hour on self-hosted
        "completion": 0.0000,
        "reasoning": 0.0000,
    },
    "ollama": {
        "prompt": 0.0000,
        "completion": 0.0000,
        "reasoning": 0.0000,
    },
}


def calculate_cost(
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int = 0,
) -> float:
    """Calculate query financial cost in USD."""
    provider_rates = RATES_PER_MILLION.get(provider.lower()) or RATES_PER_MILLION["gemini"]
    p_cost = (prompt_tokens / 1_000_000.0) * provider_rates["prompt"]
    c_cost = (completion_tokens / 1_000_000.0) * provider_rates["completion"]
    r_cost = (reasoning_tokens / 1_000_000.0) * provider_rates.get(
        "reasoning", provider_rates["completion"]
    )
    return round(p_cost + c_cost + r_cost, 6)
