---
name: numeric-verification
description: Rigorous protocol for arithmetic calculations, pricing estimates, and capacity budgeting from retrieved evidence.
---

# Numeric Verification Skill

When user inquiries involve pricing, cost accounting, memory sizing, or throughput:

1. **Evidence First**:
   - Extract raw numerical rates, unit prices, or sizing constants directly from official docs (`provider_pricing.md`, `deployment_runbook.md`).
   - Never fabricate or guess pricing rates.

2. **Mandatory Calculator Execution**:
   - For all multiplications, additions, and division of token or hardware costs, invoke `calculator` with the explicit expression.
   - Do not perform mental arithmetic in the thought stream.

3. **Units and Precision**:
   - Explicitly state intermediate units (e.g. `$ / 1M tokens`, `MB/sec`, `GiB RAM`).
   - Round financial results to 4 decimal places for unit costs, or 2 decimal places for aggregate totals.
