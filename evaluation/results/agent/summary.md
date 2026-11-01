| model | EX | 95% CI | EX relaxed | exec ok | blocked | cost $ | s/q |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | **89.2%** | 82.9%–95.0% | 95.1% | 98.0% | 0.0% | 0.452 | 9.2 |
| openai/gpt-oss-120b | **86.3%** | 79.2%–92.4% | 87.3% | 97.1% | 0.0% | 0.070 | 60.3 |
| openai/gpt-5.4-nano-2026-03-17 | **85.3%** | 77.5%–92.5% | 96.1% | 99.0% | 0.0% | 0.160 | 5.7 |
| gemini-3.6-flash | **79.4%** | 70.7%–87.3% | 94.1% | 99.0% | 0.0% | 0.585 | 6.5 |
| ibm/granite-4.0-h-small | **3.9%** | 0.9%–8.2% | 3.9% | 12.7% | 0.0% | 1.001 | 19.0 |

**EX by category**

| model | agg | filter | hard | join | lookup | m2m | neg | range | semantic | sparse | text | topk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 100% | 100% | 57% | 79% | 83% | 89% | 100% | 100% | 50% | 75% | 100% | 100% |
| openai/gpt-oss-120b | 100% | 93% | 57% | 79% | 100% | 67% | 75% | 100% | 75% | 75% | 100% | 100% |
| openai/gpt-5.4-nano-2026-03-17 | 100% | 100% | 86% | 57% | 33% | 89% | 100% | 100% | 50% | 100% | 89% | 100% |
| gemini-3.6-flash | 100% | 100% | 43% | 57% | 17% | 67% | 100% | 100% | 50% | 75% | 100% | 100% |
| ibm/granite-4.0-h-small | 8% | 14% | 0% | 0% | 0% | 0% | 0% | 17% | 0% | 0% | 0% | 0% |

**Unanswerable / adversarial**

| model | fabricated rows | unsafe SQL emitted | unsafe SQL executed | unbounded |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 20% of 5 | 0/9 | 0/9 | 0 |
| openai/gpt-oss-120b | 0% of 5 | 0/9 | 0/9 | 0 |
| openai/gpt-5.4-nano-2026-03-17 | 0% of 5 | 0/9 | 0/9 | 0 |
| gemini-3.6-flash | 0% of 5 | 0/9 | 0/9 | 0 |
| ibm/granite-4.0-h-small | 0% of 5 | 0/9 | 0/9 | 0 |
