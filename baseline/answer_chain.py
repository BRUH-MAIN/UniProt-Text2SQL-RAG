"""SQL result -> natural-language answer, via a single Gemini call."""
import os
from typing import Any

from google import genai

# Override via GEMINI_MODEL in .env if this default is ever deprecated.
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

PROMPT_TEMPLATE = """You are a precise and knowledgeable protein database expert.
Write a natural language response that:
1. Stays within 100 words.
2. Includes only relevant protein information from the query result below.
3. Uses accurate scientific terminology.
4. Avoids speculation, unnecessary detail, or elaboration.
5. Answers the question directly and succinctly.
6. Does not repeat the SQL query in your response.

Original question:
{question}

SQL query executed:
{sql}

Query result:
{rows}

Response:"""


def generate_answer(question: str, sql: str, rows: list[dict[str, Any]]) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = PROMPT_TEMPLATE.format(question=question, sql=sql, rows=rows)
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return response.text
