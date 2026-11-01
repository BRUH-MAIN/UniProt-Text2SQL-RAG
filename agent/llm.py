"""Minimal, provider-agnostic chat interface.

The agent only needs `complete(messages) -> LLMResponse`, so any model that can follow a
"reply with one JSON object" instruction can drive it - including the open-weight models
that lack reliable native tool calling. Three backends:

  GeminiLLM  - Google AI Studio (what the deployed app uses)
  ProxyLLM   - Kaggle Benchmarks model proxy (OpenAI-compatible; used for the evaluation,
               it reports the real metered cost of every call)
  ScriptedLLM- canned replies, for tests
"""
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

Messages = list[dict[str, str]]

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0


class LLM(Protocol):
    name: str

    def complete(self, messages: Messages) -> LLMResponse: ...


def strip_reasoning(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


class ProxyLLM:
    """Kaggle Benchmarks model proxy. Needs MODEL_PROXY_URL / MODEL_PROXY_API_KEY
    (written to .env by `kaggle benchmarks init`); the key is short-lived."""

    RETRYABLE = ("429", "500", "502", "503", "504", "timeout", "timed out", "overloaded", "connection")
    AUTH_ERRORS = ("401", "unauthorized", "expired", "invalid api key")
    _refresh_lock = threading.Lock()

    def __init__(self, model: str, *, reasoning: str = "low", max_attempts: int = 4, env_file: str | None = None):
        """`env_file`: the .env written by `kaggle benchmarks init`. The proxy key lasts about an hour, so when
        it is given the adapter re-runs `init` (needs KAGGLE_USERNAME/KAGGLE_KEY) on a 401 and carries on."""
        self.name, self.reasoning, self.max_attempts = model, reasoning, max_attempts
        self.env_file = Path(env_file) if env_file else None
        if self.env_file and self.env_file.exists():
            self._load_env()
        self._build_client()

    def _load_env(self) -> None:
        from dotenv import dotenv_values

        os.environ.update({k: v for k, v in dotenv_values(self.env_file).items() if v is not None})

    def _build_client(self) -> None:
        import openai

        url, key = os.environ.get("MODEL_PROXY_URL"), os.environ.get("MODEL_PROXY_API_KEY")
        if not url or not key:
            raise RuntimeError("MODEL_PROXY_URL / MODEL_PROXY_API_KEY not set - run `kaggle benchmarks init`")
        base = url.rstrip("/")
        for suffix in ("/openapi", "/genai"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        self.client = openai.OpenAI(api_key=key, base_url=base + "/openapi", timeout=180)
        self._key = key

    def _refresh_credentials(self) -> bool:
        if not self.env_file or not shutil.which("kaggle"):
            return False
        with self._refresh_lock:  # many worker threads can hit the 401 at once; refresh once
            if os.environ.get("MODEL_PROXY_API_KEY") == self._key:
                r = subprocess.run(["kaggle", "benchmarks", "init", "-y"], cwd=self.env_file.parent,
                                   capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    return False
                self._load_env()
            self._build_client()
        return True

    @staticmethod
    def _fold_system(messages: Messages) -> Messages:
        """Send instructions as part of the first user turn. Through the proxy, a system message combined
        with reasoning_effort="low" made some models return a choice with no message at all."""
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [dict(m) for m in messages if m["role"] != "system"]
        if system and rest and rest[0]["role"] == "user":
            rest[0]["content"] = system + "\n\n---\n\n" + rest[0]["content"]
        return rest or [dict(m) for m in messages]

    def complete(self, messages: Messages) -> LLMResponse:
        messages = self._fold_system(messages)
        last: Exception | None = None
        spent = tin = tout = 0
        empties = 0
        t_start = time.perf_counter()
        for attempt in range(self.max_attempts + 2):
            try:
                r = self.client.chat.completions.create(
                    model=self.name, messages=messages, reasoning_effort=self.reasoning)
                u = r.usage
                cost = getattr(u, "cost", None) or (u.model_extra or {}).get("cost") or {}
                spent += ((cost.get("input_tokens_cost_nanodollars") or 0)
                          + (cost.get("output_tokens_cost_nanodollars") or 0)) / 1e9
                tin, tout = tin + u.prompt_tokens, tout + u.completion_tokens
                msg = r.choices[0].message if r.choices else None
                text = strip_reasoning(msg.content or "") if msg else ""
                if not text and empties < 2:  # empty reply: ask again (every attempt is metered)
                    empties += 1
                    continue
                return LLMResponse(text, tin, tout, spent, time.perf_counter() - t_start)
            except Exception as e:  # noqa: BLE001
                last = e
                msg_l = str(e).lower()
                if any(a in msg_l for a in self.AUTH_ERRORS) and self._refresh_credentials():
                    continue
                if attempt >= self.max_attempts - 1 or not any(x in msg_l for x in self.RETRYABLE):
                    break
                time.sleep(5 * 3 ** attempt)
        raise RuntimeError(f"{self.name}: {type(last).__name__}: {str(last)[:300]}") from last


class GeminiLLM:
    """Google AI Studio via google-genai. Pin GEMINI_MODEL to a specific version: a floating
    alias such as `*-latest` makes results irreproducible."""

    def __init__(self, model: str | None = None):
        from google import genai

        self.name = model or os.environ["GEMINI_MODEL"]
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def complete(self, messages: Messages) -> LLMResponse:
        from google.genai import types

        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part(text=m["content"])])
                    for m in messages if m["role"] != "system"]
        t0 = time.perf_counter()
        r = self.client.models.generate_content(
            model=self.name, contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0))
        meta = r.usage_metadata
        return LLMResponse(r.text or "", getattr(meta, "prompt_token_count", 0) or 0,
                           getattr(meta, "candidates_token_count", 0) or 0, 0.0, time.perf_counter() - t0)


class ScriptedLLM:
    """Replies from a fixed list (or callable), recording what it was sent. For tests."""

    def __init__(self, replies, name: str = "scripted"):
        self.name, self.calls = name, []
        self._replies = replies

    def complete(self, messages: Messages) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        i = len(self.calls) - 1
        text = self._replies(messages) if callable(self._replies) else self._replies[min(i, len(self._replies) - 1)]
        return LLMResponse(text, input_tokens=len(str(messages)) // 4, output_tokens=len(text) // 4)
