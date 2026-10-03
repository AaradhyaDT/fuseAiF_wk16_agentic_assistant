# Evaluation Policy & Failure Taxonomy Guidelines

## Architectural Purpose
To provide deterministic standards for evaluating autonomous agentic loops within the AI Fellowship ecosystem.

## Trajectory Efficiency Standards
- **Single-Hop Query**: Expected trajectory length $\le 3$ iterations. Trajectories $\ge 5$ iterations are flagged as inefficient (`over_long`).
- **Multi-Hop / Comparative Query**: Expected trajectory length $3 \le \text{iters} \le 6$.
- **Hard Maximum Stop**: The execution harness strictly enforces `agent_max_iterations = 8`.

## Three-Tier Failure Taxonomy
1. **Hard Failure**: Catastrophic termination with no usable output. Includes unhandled exceptions, provider fallback exhaustion, loop detector aborts, or hitting the hard iteration cap without a terminal tool call.
2. **Soft Failure**: The agent terminates gracefully and emits an answer, but the answer contains factual errors, omits mandatory facts, misses required citations, or selects the wrong terminal action.
3. **Cascading Soft Failure**: A soft failure where the terminal inaccuracy was directly caused by an unrecovered error in an intermediate tool step (e.g. accepted empty search results without retrying, misread calculator inputs, or relied on hallucinated parameters).
