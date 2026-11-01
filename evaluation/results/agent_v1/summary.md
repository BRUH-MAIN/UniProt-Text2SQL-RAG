| model | EX | 95% CI | EX relaxed | exec ok | blocked | cost $ | s/q |
|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | **78.4%** | 70.3%–86.1% | 83.3% | 85.3% | 0.0% | 0.473 | 9.9 |

**EX by category**

| model | agg | filter | hard | join | lookup | m2m | neg | range | semantic | sparse | text | topk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 85% | 93% | 57% | 57% | 83% | 56% | 88% | 100% | 25% | 100% | 89% | 100% |

**Unanswerable / adversarial**

| model | fabricated rows | unsafe SQL emitted | unsafe SQL executed | unbounded |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 0% of 5 | 0/9 | 0/9 | 0 |
