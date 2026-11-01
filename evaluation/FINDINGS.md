## Summary

*Hand-written from the tables below; every figure here appears in them. Read the caveats at the end before quoting any of it.*

1. **Telling the model how the data is stored was the biggest lever.** Appending the column notes (`db/annotations.sql`)
   to the original prompt raised strict EX for all six models, by +2.9 to +7.8 points. The interval excludes zero for both
   Gemini models (flash-lite +6.9, 3.6-flash +7.8). It adds 62–75% to the input tokens of each call and no extra calls;
   total cost moved between −23% and +60% depending on the model, because reasoning tokens dominate the bill.
2. **The agent did not beat the annotated prompt on accuracy.** On strict EX it was lower for gemini-3.5-flash-lite (−6.9,
   resolved), gemini-3.6-flash (−15.7, resolved) and Granite (−34.3, resolved), and indistinguishable for gpt-5.4-nano (+2.0)
   and gpt-oss-120b (−3.9). Against the *original* baseline it is indistinguishable for four models and much worse for Granite.
   Much of the strict gap is the agent returning the right data with extra columns (3.6-flash: 15 of its 21 strict misses);
   on relaxed EX (not significance-tested) it is within 2–3 points of the annotated prompt for the Gemini models, ahead for nano
   (96% vs 88%) and behind for gpt-oss (87% vs 93%).
3. **What the agent does buy is behavioural.** On the 5 unanswerable questions it fabricated rows 0–1 times per model, against
   1–5 for the single-shot arms. It emitted unsafe SQL in 0 of 45 adversarial trials (5 models × 9). Every one of the six
   models emitted unsafe SQL on at least one of the 9 adversarial requests under the original prompt (`pg_sleep(60)`, a
   `CREATE TABLE` copy, and for Granite `DELETE`/injection), and five of six still did with the notes added. Its answers contain only numbers and accessions found in its query
   results 97–100% of the time for the four capable models.
4. **It costs more and needs a capable model.** 1.6–4.3× the annotated prompt per question in money (flash-lite $0.45 vs
   $0.23, nano $0.16 vs $0.04) and 2.3–4.0× in latency (9.2 s vs 2.3 s for flash-lite). With Granite, a small open model, the loop
   fell apart: 89 of 102 answerable questions ended as "declined" or "step budget exhausted".
5. **The stricter guard is free on this benchmark:** re-scoring each model's baseline SQL through it changed no result.

### Practical reading

For accuracy per dollar, the best configuration measured is the *annotated single-shot prompt behind the hardened guard and
executor*. The agent is the right choice when refusing to guess and checking the answer against the data matter more than
cost, and only with a capable instruction-following model.

### Caveats that matter

* **The annotated arm is author-informed.** The same person wrote the column notes and the benchmark's trap questions, so part
  of the "annotated" gain is "told about the quirks the benchmark probes". Whether notes help on unseen question types is untested.
* **The safety comparison mixes two things.** The agent arm runs on the hardened guard/executor and the single-shot arms on the
  legacy ones, so "unsafe SQL executed" differs partly because of the stack. "Unsafe SQL *emitted*" and "fabricated rows" are model
  behaviour and are not affected by the stack.
* **Agent v1 → v2.** The first agent run lost points to brittle reply parsing; the parser was fixed after seeing those failures
  (disclosed above). No prompt or tool was changed after seeing results, and none was tuned on this benchmark.
* **Not run:** the agent arm for Claude Sonnet 5 (a single-shot arm alone cost $0.91–$1.42; the agent arm would cost several
  times that). One run per model, no seed variance, 102 answerable questions: gaps under ~8 points between two models are noise.
* **"Fabricated" is strict:** any returned row on an unanswerable question counts, including a plausible-looking partial match.
* **Grounding is conservative:** a correct number the model *derived* (12000 − 11597 = 403) is flagged as unverifiable.
