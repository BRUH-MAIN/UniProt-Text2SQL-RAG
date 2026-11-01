"""NL question -> SQL, via a single Gemini call."""
import os

from google import genai

# Override via GEMINI_MODEL in .env if this default is ever deprecated.
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

PROMPT_TEMPLATE = """You are a PostgreSQL expert. Given the table schema below, \
write a single read-only SQL query (SELECT only) that answers the user's question.

Rules:
- Output ONLY the SQL query, no explanation, no markdown code fences.
- Use only tables/columns that appear in the schema below.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or TRUNCATE statements.

Schema:
{schema}

Question: {question}

SQL query:"""


def generate_sql(question: str, schema: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = PROMPT_TEMPLATE.format(schema=schema, question=question)
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return response.text
