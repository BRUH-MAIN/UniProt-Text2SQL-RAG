"""Gradio front-end for the UniProt SQL agent."""
import os

import gradio as gr
import pandas as pd
import spaces
from dotenv import load_dotenv

from agent.database import ReadOnlyDB
from agent.llm import GeminiLLM
from agent.loop import run_agent
from agent.ratelimit import RateLimiter

load_dotenv()

MAX_QUESTION_CHARS = 500
LIMITER = RateLimiter(per_client=int(os.environ.get("RATE_PER_CLIENT", "15")),
                      global_limit=int(os.environ.get("RATE_GLOBAL", "150")))

CONFIG_ERROR = None
STARTUP_WARNINGS: list[str] = []
DB: ReadOnlyDB | None = None
LLM: GeminiLLM | None = None
missing = [v for v in ("GEMINI_API_KEY", "GEMINI_MODEL", "DATABASE_URL") if not os.environ.get(v)]
if missing:
    CONFIG_ERROR = (f"Missing configuration: {', '.join(missing)}. Set them as environment variables "
                    "(a local .env file, or HF Space secrets in production). GEMINI_MODEL must be a pinned "
                    "model id, not a '*-latest' alias.")
else:
    DB = ReadOnlyDB()
    LLM = GeminiLLM()
    STARTUP_WARNINGS = DB.privilege_warnings()
    if "latest" in LLM.name:
        STARTUP_WARNINGS.append(f"GEMINI_MODEL={LLM.name!r} is a floating alias; pin a version for reproducibility.")


def _client_id(request: gr.Request | None) -> str:
    if request is None:
        return "local"
    fwd = request.headers.get("x-forwarded-for") if request.headers else None
    return (fwd.split(",")[0].strip() if fwd else request.client.host) or "unknown"


@spaces.GPU
def ask(question: str, request: gr.Request = None):
    """This Space runs on ZeroGPU hardware, which requires at least one @spaces.GPU function to boot;
    the app makes no GPU calls (it is a Gemini + Postgres client), so the decorator is a no-op."""
    empty = pd.DataFrame()
    if CONFIG_ERROR:
        return CONFIG_ERROR, "", "", empty
    question = (question or "").strip()
    if not question:
        return "Please enter a question.", "", "", empty
    if len(question) > MAX_QUESTION_CHARS:
        return f"Please keep questions under {MAX_QUESTION_CHARS} characters.", "", "", empty
    allowed, why = LIMITER.allow(_client_id(request))
    if not allowed:
        return why, "", "", empty

    try:
        res = run_agent(question, LLM, DB)
    except Exception as e:  # noqa: BLE001 - surface provider/db outages as a message, not a stack trace
        return f"The agent failed: {type(e).__name__}: {str(e)[:200]}", "", "", empty

    trace = "\n".join(
        f"{s.n}. **{s.action}** {'' if s.ok else '(failed) '}— {s.thought}" for s in res.steps)
    if res.outcome == "answered":
        answer = res.answer
        if res.grounding and not res.grounding.ok:
            answer += f"\n\n⚠️ Check against the table below — {res.grounding.describe()}."
        if res.truncated:
            answer += f"\n\nℹ️ The query matched more than {len(res.rows)} rows; only the first {len(res.rows)} are shown."
    elif res.outcome == "declined":
        answer = f"I can't answer that from this database. {res.answer}"
    else:
        answer = "I couldn't reach an answer within the step limit. Try rephrasing or narrowing the question."
    table = pd.DataFrame(res.rows, columns=res.columns) if res.rows else empty
    return answer, res.sql or res.last_sql or "", trace, table


with gr.Blocks(title="UniProt SQL Agent") as demo:
    gr.Markdown(
        "# UniProt SQL Agent\n"
        "Ask a question about ~12,000 reviewed human UniProt proteins. An LLM agent inspects the schema, "
        "looks up the exact stored values, runs **read-only** SQL against Postgres and answers from the rows. "
        "Every step is shown below, and numbers in the answer are checked against the result.")
    if CONFIG_ERROR:
        gr.Markdown(f"⚠️ **{CONFIG_ERROR}**")
    for w in STARTUP_WARNINGS:
        gr.Markdown(f"⚠️ **Deployment warning:** {w}")

    question_box = gr.Textbox(label="Question", lines=2, max_lines=4,
                              placeholder="e.g. Which 5 proteins have the most recorded interactions?")
    submit_btn = gr.Button("Ask", variant="primary")
    answer_box = gr.Markdown(label="Answer")
    with gr.Accordion("Agent steps", open=False):
        trace_box = gr.Markdown()
    with gr.Accordion("SQL", open=False):
        sql_box = gr.Code(language="sql", interactive=False)
    result_table = gr.Dataframe(label="Result rows")

    outputs = [answer_box, sql_box, trace_box, result_table]
    submit_btn.click(ask, inputs=question_box, outputs=outputs)
    question_box.submit(ask, inputs=question_box, outputs=outputs)

if __name__ == "__main__":
    demo.launch()
