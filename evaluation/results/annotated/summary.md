| model | EX | 95% CI | EX relaxed | exec ok | blocked | cost $ | s/q |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | **96.1%** | 91.8%–99.1% | 97.1% | 100.0% | 0.0% | 0.233 | 2.3 |
| gemini-3.6-flash | **95.1%** | 90.3%–99.0% | 97.1% | 100.0% | 0.0% | 0.362 | 2.5 |
| anthropic/claude-sonnet-5@default | **90.2%** | 83.8%–95.3% | 95.1% | 100.0% | 0.0% | 1.424 | 1.5 |
| openai/gpt-oss-120b | **90.2%** | 83.8%–95.3% | 93.1% | 99.0% | 0.0% | 0.032 | 26.3 |
| openai/gpt-5.4-nano-2026-03-17 | **83.3%** | 76.2%–90.1% | 88.2% | 99.0% | 0.0% | 0.037 | 1.6 |
| ibm/granite-4.0-h-small | **38.2%** | 29.0%–48.1% | 38.2% | 83.3% | 0.0% | 0.265 | 5.4 |

**EX by category**

| model | agg | filter | hard | join | lookup | m2m | neg | range | semantic | sparse | text | topk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 100% | 100% | 71% | 93% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 88% |
| gemini-3.6-flash | 100% | 86% | 86% | 86% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| anthropic/claude-sonnet-5@default | 100% | 79% | 71% | 79% | 100% | 100% | 100% | 100% | 50% | 100% | 100% | 100% |
| openai/gpt-oss-120b | 100% | 86% | 71% | 79% | 100% | 89% | 100% | 100% | 50% | 100% | 100% | 100% |
| openai/gpt-5.4-nano-2026-03-17 | 92% | 86% | 57% | 64% | 83% | 100% | 100% | 100% | 50% | 100% | 89% | 75% |
| ibm/granite-4.0-h-small | 38% | 86% | 14% | 50% | 67% | 11% | 12% | 33% | 0% | 100% | 11% | 12% |

**Unanswerable / adversarial**

| model | fabricated rows | unsafe SQL emitted | unsafe SQL executed | unbounded |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 60% of 5 | 2/9 | 1/9 | 0 |
| gemini-3.6-flash | 60% of 5 | 1/9 | 1/9 | 0 |
| anthropic/claude-sonnet-5@default | 40% of 5 | 1/9 | 1/9 | 0 |
| openai/gpt-oss-120b | 40% of 5 | 2/9 | 2/9 | 0 |
| openai/gpt-5.4-nano-2026-03-17 | 100% of 5 | 0/9 | 0/9 | 0 |
| ibm/granite-4.0-h-small | 60% of 5 | 2/9 | 0/9 | 0 |
