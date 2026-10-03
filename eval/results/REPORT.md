# W16 Agentic Evaluation Report

- **Run ID**: `eval_none_cleared_20261003_154842`
- **Fault Mode**: `none`
- **Tool Result Clearing Enabled**: `True`
- **Total Test Cases**: 4

## 1. Executive Summary & Core Metrics

| Metric | Result | Benchmark Target | Status |
|---|---|---|---|
| **Task Completion Rate** | **75.0%** (3/4) | $\ge 80.0\%$ | ⚠️ WARN |
| **Tool-Call Correctness** | **91.7%** | $\ge 90.0\%$ | ✅ PASS |
| **Mean Trajectory Length** | **3.50 iters** | $\le 4.5$ iters | ✅ OPTIMAL |
| **Over-Long Trajectories** | **1 cases** | $0$ | ⚠️ FLAGGED |
| **Total Tokens Consumed** | **24,988** (prompt: 22,790, out: 1,265, think: 933) | Bounded | ✅ MEASURED |
| **Total Financial Cost** | **$0.0047 USD** | $< $0.10 USD | ✅ VERIFIED |

## 2. Failure Taxonomy Breakdown

| Failure Tier | Occurrences | Definition |
|---|---|---|
| **Hard Failure** | 1 | Catastrophic halt: budget/iteration cap, loop abort, provider crash |
| **Soft Failure** | 0 | Graceful halt, but missed facts, missing citations, or wrong terminal action |
| **Cascading Soft Failure** | 0 | Flawed final answer caused directly by unrecovered intermediate tool error |

## 3. Performance by Evaluation Category

| Category | Cases | Passed | Pass Rate | Mean Iters | Mean Cost ($) |
|---|---|---|---|---|---|
| `multihop` | 1 | 1 | 100.0% | 6.00 | $0.0023 |
| `single_hop` | 3 | 2 | 66.7% | 2.67 | $0.0008 |

## 4. Per-Query Execution Log

| ID | Category | Status | Iters | Tool Correctness | Tokens | Cost ($) | Failure Tier | Notes / Root Cause |
|---|---|---|---|---|---|---|---|---|
| `single_hop_01` | `single_hop` | ✅ PASS | 3 | 67% | 5,375 | $0.0011 | `none` | Clean execution |
| `single_hop_02` | `single_hop` | ❌ FAIL | 3 | 100% | 3,740 | $0.0006 | `hard` | Hard termination: provider_failure |
| `single_hop_03` | `single_hop` | ✅ PASS | 2 | 100% | 3,512 | $0.0007 | `none` | Clean execution |
| `multihop_01` | `multihop` | ✅ PASS | 6 | 100% | 12,361 | $0.0023 | `none` | Clean execution |

## 5. Comparative Analysis: W16 Agentic Loop vs. W15 Single-Pass Baseline

| Architecture | Completion Rate | Mean Iters | Total Tokens | Total Cost ($) | Conflict Resolution | Verification Gate |
|---|---|---|---|---|---|---|
| **W15 Classic RAG (Baseline)** | 0.0% (0/4) | 1.0 | 2,568 | $0.0006 | ❌ Fails on superseded docs | ❌ None (hallucination risk) |
| **W16 Verified Agent (Ours)** | **75.0%** (3/4) | 3.50 | 24,988 (9.7x) | $0.0047 (7.4x) | ✅ Full precedence enforcement | ✅ Deterministic check |

> **Coordination Cost Rationale**: The agentic loop uses approximately 9.7x tokens compared to the single-pass baseline. This modest cost difference buys autonomous multi-hop cross-referencing, self-verification, and resilience against outdated specifications.