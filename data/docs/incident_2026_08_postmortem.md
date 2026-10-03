# Postmortem: Incident INC-4091 (August 24, 2026)

## Executive Summary
On August 24, 2026, at 14:12 UTC, the assistant API experienced a 14-minute outage causing `429 Too Many Requests` cascades and premature circuit breaker trips across all healthy providers.

## Root Cause
1. **Bursty Client Traffic**: A batch testing script issued 45 concurrent requests within 1.2 seconds, overwhelming the default `rate_limit_burst=5` setting.
2. **Circuit Breaker False Positives**: Downstream 429 status codes were incorrectly categorized as provider hardware outages, tripping the Gemini circuit breaker to `open` state.

## Preventative Actions & Permanent Mitigations
- Adjusted `RATE_LIMIT_BURST` from 5 to 20 in production configuration.
- Standardized `RATE_LIMIT_RPM` at 60.
- Implemented exponential backoff with random jitter in client SDK callers.
