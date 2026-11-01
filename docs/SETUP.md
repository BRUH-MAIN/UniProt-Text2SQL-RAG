# Setup guide

## 1. Get API keys / provision services

**Gemini API key** - free tier, no credit card required:
1. Go to https://aistudio.google.com/apikey and create a key.
2. Put it in `.env` as `GEMINI_API_KEY`.
3. Choose a **pinned** model id (not a `*-latest` alias, which silently changes behaviour and makes results
   irreproducible) and put it in `.env` as `GEMINI_MODEL`. `app.py` refuses to start without it. Pick one that has
   free-tier quota on your account (`google.genai.Client().models.list()`); `evaluation/RESULTS.md` says which
   models were measured.

**Postgres database** - either works, pick one:
- [Neon](https://neon.tech) - generous free tier, plain Postgres.
- [Supabase](https://supabase.com) - free tier has historically had a tighter
  (~500MB) storage cap; check current limits before committing to it.

Create a project/database, then copy its connection string into `.env` as
both `DATABASE_URL` and `INGEST_DATABASE_URL` for now (you'll swap
`DATABASE_URL` to a read-only role in step 4, after ingestion).

## 2. Local environment

```bash
python -m venv .venv
.venv/Scripts/activate        # .venv\Scripts\Activate.ps1 on PowerShell
pip install -r requirements-ingest.txt   # includes requirements.txt + ingestion deps
cp .env.example .env
```

Fill in `.env`: `GEMINI_API_KEY`, `GEMINI_MODEL`, `DATABASE_URL`, `INGEST_DATABASE_URL`.

## 3. Create the schema and ingest data

```bash
python -m db.init_db
```

Creates all 20 tables from `db/schema.sql` and attaches the column notes in `db/annotations.sql`
(what each column really contains; the agent reads them through `describe_table`).

```bash
python -m ingest.fetch_uniprot
```

Downloads a reviewed (Swiss-Prot) UniProt subset (defaults to human,
`reviewed:true AND organism_id:9606`, ~20k entries) to
`data/uniprot_subset.dat.gz`. Override with `--query` for a different
organism/scope.

Before running the full load, validate on a small sample:

```bash
INGEST_LIMIT=50 python -m ingest.parse_and_load
```

Check row counts look sane (`SELECT count(*) FROM proteins;` etc. via your
provider's SQL console), then run the full load:

```bash
python -m ingest.parse_and_load --truncate   # --truncate wipes prior data first
```

Re-running without `--truncate` is safe: each protein's rows are replaced, not appended.

`INGEST_LIMIT` (default 12000, set in `.env`) caps how many records are
loaded regardless of how many the UniProt query matched - this decouples
"how much data to load" from tuning exact UniProt query syntax.

After loading, sanity-check size against your provider's free-tier cap:

```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
```

If it's too large, lower `INGEST_LIMIT` or narrow the `--query` and rerun
`parse_and_load.py --truncate`.

## 4. Create a read-only role for the app

The app should never connect with a role that can write. In your Postgres
provider's SQL console, run (replace `<db>` and the password):

```sql
CREATE ROLE app_readonly WITH LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE <db> TO app_readonly;
GRANT USAGE ON SCHEMA public TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO app_readonly;
```

Build a connection string using these credentials and set it as
`DATABASE_URL` in `.env` (keep `INGEST_DATABASE_URL` pointing at the
original, privileged role - only `db/init_db.py` and `ingest/` use it).

## 5. Run locally

```bash
python app.py
```

This starts a local Gradio server (default http://127.0.0.1:7860).

**Manual smoke test** - ask a few real questions and confirm the flow works
end to end:
- "What is the function of protein P01308?"
- "How many proteins belong to the protein kinase superfamily?"
- "Which tissues is BRCA1 expressed in?" (not in the schema: it should decline, not invent)

Open "Agent steps" and "SQL": the answer must follow from the rows shown. A ⚠️ under the answer means a number
or accession in it does not appear in the result. Also try a destructive request (e.g. "delete all proteins") and
confirm it is declined or rejected, never executed. On startup the app prints a deployment warning if the
database role is not least-privilege.

**No cloud account?** Everything also runs against a local PostgreSQL (16+):
`conda create -n uniprot -c conda-forge python=3.12 postgresql`, `initdb`, `createdb uniprot`, then follow steps 3-4
against `postgresql://<you>@localhost:5432/uniprot`. This is how the evaluation database is built.

## 6. Deploy to Hugging Face Spaces

This app needs no GPU and no local model - it's outbound HTTPS calls to
Gemini and Postgres - so in principle `cpu-basic` hardware is more than
enough. In practice, as of mid-2026, Hugging Face requires a **PRO
subscription** to create *or* downgrade to a `cpu-basic` Gradio Space via the
API/CLI (`402 Payment Required`); only static (HTML-only) Spaces are free
through that path, which can't hold this app's secrets. Creating a Space
through the **website UI** worked on a free account and defaulted to
`zero-a10g` (ZeroGPU) hardware - if that happens to you too, you need two
extra things beyond a normal Gradio Space to make it boot:

1. **Create the Space via the website** (huggingface.co/new-space), SDK:
   **Gradio**. Note the hardware it lands on (`hf spaces info <ns>/<name>
   --expand runtime`) - if it's `cpu-basic`, skip straight to step 4.
2. **If it's `zero-a10g`**: ZeroGPU Spaces refuse to start unless at least one
   function is decorated `@spaces.GPU` (`No @spaces.GPU function detected
   during startup`). This repo's `app.py` already decorates
   `ask` with a no-op `@spaces.GPU` purely to satisfy that
   check - it makes no GPU calls, so functionally nothing changes, but the
   `spaces` package must be installed (`requirements.txt` already includes
   it). Don't pin `gradio` to an old version if you edit `requirements.txt`
   further - `gradio-client` versions before ~5.x cap `websockets<13.0`,
   which conflicts with `google-genai`'s `websockets>=13.0` requirement.
   Check the current latest with `pip index versions gradio` and keep the
   floor recent.
3. **If you hit a Unicode/`charmap` codec crash on startup**: set
   `PYTHONIOENCODING=utf-8` as a Space **variable** (not secret) -
   `hf spaces variables add <ns>/<name> -e PYTHONIOENCODING=utf-8` - and
   restart. (On Windows, also export it for the `hf` CLI's own local
   commands if *those* crash printing Unicode: `PYTHONIOENCODING=utf-8 hf
   ...`.)
4. Push the code. Either `git push` to the Space's git remote, or
   `hf upload <ns>/<name> . --repo-type space` (add `--exclude` patterns for
   `.venv`, `.env`, `.git`, `data/`, `__pycache__` - if `--exclude` globs get
   mangled by your shell, the `huggingface_hub` Python API's
   `HfApi().upload_folder(..., ignore_patterns=[...])` is more reliable).
5. In the Space's **Settings → Variables and secrets**, add secrets
   `GEMINI_API_KEY` and `DATABASE_URL` (the **read-only** connection string
   from step 4 above) and the variable `GEMINI_MODEL` (pinned id). The demo spends your
   quota on every request, so it rate-limits per client and globally; tune with the
   `RATE_PER_CLIENT` (default 15/hour) and `RATE_GLOBAL` (default 150/hour) variables.
6. Wait for it to build (`hf spaces wait <ns>/<name>`), then check logs
   (`hf spaces logs <ns>/<name>`) and re-run the smoke-test questions from
   step 5 against the live Space via `gradio_client.Client("<ns>/<name>",
   token=...)`.
