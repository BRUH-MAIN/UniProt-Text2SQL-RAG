# Design decisions and known limitations

Everything below was measured against the database this repository builds, not assumed.

## Why an agent, and why not "RAG"

The original version of this project was named RAG, but it had no retrieval step: the whole
7 KB DDL was pasted into one prompt, the model wrote SQL once, and that was it.

The schema (20 tables) is small enough that embedding-based retrieval would add machinery
without adding information. What the model actually lacks is *knowledge about the data*:
the exact spelling of stored values (`'Homo sapiens (Human)'`, not `'Homo sapiens'`), columns
that hold something other than their name suggests (`interactions.interaction_type` is
`NbExp=18`), and columns that are never filled. An agent can look those things up, run its
query, read the error and try again. That is what `agent/` does: a bounded loop over four
read-only tools (`list_tables`, `describe_table`, `search_values`, `run_sql`).

Whether that is *better* than a single prompt is an empirical question, so the repository keeps
the original single-shot pipeline in `baseline/` and compares three arms on the same benchmark
(see `evaluation/RESULTS.md`): the original, the original plus schema annotations, and the agent.

The result is mixed and should be quoted as such. The schema annotations alone gave most of the accuracy gain; the agent
came within a few points of them on a relaxed metric for three of four capable models (not gpt-oss) but not on the strict one, cost 1.6–4.3× more, and failed outright with a
weak model. Its measurable advantages are refusing to fabricate answers to unanswerable questions, never emitting unsafe SQL
in the hostile trials, and grounded answers. If only accuracy per dollar mattered, the annotated single-shot prompt behind the
same guard and executor would be the better choice.

## What the agent does not do

* It does not retrieve from documents or embeddings. All answers come from SQL over the loaded tables.
* It cannot answer anything outside the 20 tables (structures, expression, GO terms, orthologs, ...).
  It is instructed to decline; the benchmark measures how often it fabricates instead.
* Its step budget is fixed (8). A question that needs more exploration ends as `budget_exhausted`, not a guess.
* It is not evaluated on questions typed by real users, only on the 116 hand-written benchmark items.

## The data

| Fact | Value |
|---|---|
| Entries downloaded (reviewed, human) | 20,431 |
| Entries loaded | **12,000** — the first 12,000 in download order (`INGEST_LIMIT`), so a deterministic but non-random 59% |
| Distinct organisms | **1** (`Homo sapiens (Human)`) — `proteins.organism` carries no information |
| `taxonomic_lineage` | 168,000 rows (14 per protein) holding **one** distinct lineage |
| `toxic_doses` | **0 rows** |
| Nearly empty | `allergenic_properties` 6, `biotechnological_uses` 21, `pharmaceutical_uses` 49 |
| Never populated | `mutagenesis.effect`, `toxic_doses.measurement_unit`, `topological_domains.description` (the observed mutagenesis effect is in `mutagenesis.description`) |
| `disease_involvement` | 746 of 6,874 rows have no `disease_name`/`omim_id` (the source text did not match the parser's pattern) |
| `genes` | holds primary names *and* synonyms with no flag; 588 gene names map to more than one protein (e.g. `HTT` is a synonym of the serotonin transporter as well as the name of huntingtin) |
| `pathways` | 196 of 322 names embed step detail (`... step 2/3.`), so near-duplicates are common |
| `subcellular_locations` | free text split on `;`; 121 of 19,268 rows are fragments (`Note=...` or lower-case continuations) |

Consequence: questions about organism, lineage and toxic doses are answerable only trivially or with
"nothing is recorded", and a model that treats `interaction_type` as a category will return nonsense.
`db/annotations.sql` documents these as column comments, which the agent reads through `describe_table`.

## Loader fidelity

`ingest/parse_and_load.py` is a partial mirror of UniProt, not a complete one. It reads four feature
types and about a dozen comment topics; cross-references, keywords, EC numbers, taxon IDs, secondary
accessions and dates are discarded. Features with uncertain boundaries (`<`, `>`) are stored as exact
numbers — 3 such features among the 12,000 loaded entries. A single family (the first `Belongs to the ...`
sentence) is kept per protein.

Fixed in this version: re-running the loader without `--truncate` used to duplicate every detail row, and
`--truncate` left `genes`/`pathways`/`protein_families` behind (`tests/test_ingest_idempotent.py`).

## Schema decisions an expert would question

* `interactions.interacting_protein` is free text (`GENE (ACCESSION)`), not a foreign key to `proteins`.
* `active_sites.position` is `TEXT` while the other position columns are `INTEGER`.
* Organism and lineage are denormalised per protein instead of referencing a taxonomy table.
* `lineage_path` holds a single taxon name, not a path.
* Surrogate `INTEGER` identity keys everywhere; `BIGINT` would be needed above ~2 billion rows.

These were inherited from the original relational design and are kept so that results are comparable
with the original system; changing them would be a separate project.

## Safety model

See the README for the layers. The legacy guard was a first-keyword check built on `sqlparse`; the
red-team in `evaluation/results/redteam.md` shows what it let through (13 of 18 hostile statements).
The replacement parses the statement with PostgreSQL's own parser (`pglast`) and the database
independently enforces read-only transactions, a statement timeout and a row cap.
The guard is deliberately conservative: it rejects any `pg_*` function and any table outside the
application's 20, so it can refuse legitimate but unusual queries.

## Provenance

The 20-table schema and the first prototype (MySQL + local GGUF model + LangChain) come from a 2024 team
project (see the first commits). The ingestion pipeline, Postgres port, safety layers, agent, evaluation
harness and this document were written afterwards.
