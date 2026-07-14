# HAL Eval Report

1 runs — 1 scenarios x 1 models. Judge: fixed model, blind to candidate identity. Handled-rate excludes na (judge/harness failures).

## Overall

| Model | Handled | Partial | Failed | na | Handled-rate | Asserts | Mean $/turn | Median $/turn | Mean latency |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.6-luna | 0 | 1 | 0 | 0 | 0.0% | 1/1 | $0.0305 | $0.0305 | 4.1s |

## Handled-rate by category

| Category | gpt-5.6-luna |
|---|---|
| baby-logging | 0.0% |

## Projected monthly cost

Prod volume: **34 turns/day** (hal_turns, trailing 14 days). Projection = mean eval cost/turn x volume x 30. Eval turns skew heavier than prod (fixtures force tool loops), so treat these as an upper bound for ranking, not a bill forecast.

| Model | Mean $/turn | $/day | $/month |
|---|---|---|---|
| gpt-5.6-luna | $0.0305 | $1.04 | $31.11 |

## Recommendation

**gpt-5.6-luna** is both the best-scoring (0.0%) and the cheapest eligible model.

## Failures (partial + failed)

### gpt-5.6-luna
- `baby-log-no-phantom-claim` [baby-logging] partial (hallucination): Feed was logged via the baby tool as required, but the reply also claims a bottle prep reminder was set with no supporting tool call in the trace, plus an unexplained link.

