| model | EX | 95% CI | EX relaxed | exec ok | blocked | cost $ | s/q |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | **89.2%** | 82.7%–95.0% | 90.2% | 100.0% | 0.0% | 0.189 | 2.2 |
| anthropic/claude-sonnet-5@default | **87.3%** | 80.4%–93.1% | 92.2% | 100.0% | 0.0% | 0.913 | 1.5 |
| gemini-3.6-flash | **87.3%** | 80.2%–93.2% | 92.2% | 99.0% | 0.0% | 0.273 | 2.6 |
| openai/gpt-oss-120b | **82.4%** | 73.5%–90.2% | 84.3% | 99.0% | 1.0% | 0.020 | 17.4 |
| openai/gpt-5.4-nano-2026-03-17 | **80.4%** | 72.3%–88.1% | 85.3% | 99.0% | 0.0% | 0.048 | 1.6 |
| ibm/granite-4.0-h-small | **31.4%** | 22.2%–40.8% | 33.3% | 77.5% | 1.0% | 0.233 | 3.8 |

**EX by category**

| model | agg | filter | hard | join | lookup | m2m | neg | range | semantic | sparse | text | topk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 100% | 93% | 57% | 93% | 100% | 100% | 100% | 83% | 25% | 100% | 89% | 88% |
| anthropic/claude-sonnet-5@default | 100% | 93% | 86% | 71% | 83% | 89% | 100% | 83% | 25% | 100% | 89% | 100% |
| gemini-3.6-flash | 100% | 93% | 100% | 71% | 83% | 100% | 100% | 83% | 0% | 100% | 89% | 88% |
| openai/gpt-oss-120b | 92% | 100% | 57% | 86% | 83% | 56% | 100% | 83% | 0% | 100% | 78% | 100% |
| openai/gpt-5.4-nano-2026-03-17 | 92% | 93% | 86% | 64% | 83% | 67% | 100% | 83% | 0% | 100% | 67% | 100% |
| ibm/granite-4.0-h-small | 31% | 64% | 0% | 36% | 83% | 0% | 12% | 17% | 0% | 75% | 11% | 38% |

**Unanswerable / adversarial**

| model | fabricated rows | unsafe SQL emitted | unsafe SQL executed | unbounded |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 60% of 5 | 1/9 | 0/9 | 0 |
| anthropic/claude-sonnet-5@default | 60% of 5 | 1/9 | 0/9 | 0 |
| gemini-3.6-flash | 60% of 5 | 1/9 | 0/9 | 0 |
| openai/gpt-oss-120b | 20% of 5 | 1/9 | 0/9 | 0 |
| openai/gpt-5.4-nano-2026-03-17 | 80% of 5 | 1/9 | 0/9 | 0 |
| ibm/granite-4.0-h-small | 60% of 5 | 3/9 | 0/9 | 0 |
