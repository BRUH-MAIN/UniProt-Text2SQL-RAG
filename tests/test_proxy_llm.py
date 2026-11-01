"""ProxyLLM request shaping and failure handling, with a fake OpenAI client (no network)."""
from types import SimpleNamespace as NS

import pytest

from agent.llm import ProxyLLM


def make(responses, **kw):
    llm = ProxyLLM.__new__(ProxyLLM)
    llm.name, llm.reasoning, llm.max_attempts, llm.env_file = "m", "low", kw.get("max_attempts", 3), None
    llm.sent = []
    it = iter(responses)

    def create(**req):
        llm.sent.append(req)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    llm.client = NS(chat=NS(completions=NS(create=create)))
    return llm


def resp(text, cost=1000):
    msg = NS(content=text) if text is not None else None
    usage = NS(prompt_tokens=10, completion_tokens=5, cost={"input_tokens_cost_nanodollars": cost, "output_tokens_cost_nanodollars": cost},
               model_extra={})
    return NS(choices=[NS(message=msg)], usage=usage)


def test_system_message_is_folded_into_first_user_turn():
    llm = make([resp("ok")])
    llm.complete([{"role": "system", "content": "RULES"}, {"role": "user", "content": "Q"}])
    sent = llm.sent[0]["messages"]
    assert [m["role"] for m in sent] == ["user"] and sent[0]["content"].startswith("RULES") and sent[0]["content"].endswith("Q")
    assert llm.sent[0]["reasoning_effort"] == "low"


def test_multi_turn_keeps_later_roles():
    llm = make([resp("ok")])
    llm.complete([{"role": "system", "content": "S"}, {"role": "user", "content": "Q"},
                  {"role": "assistant", "content": "A"}, {"role": "user", "content": "OBS"}])
    assert [m["role"] for m in llm.sent[0]["messages"]] == ["user", "assistant", "user"]


def test_empty_reply_is_retried_and_all_attempts_are_metered():
    llm = make([resp(None), resp(""), resp("{\"a\":1}")])
    r = llm.complete([{"role": "user", "content": "Q"}])
    assert r.text == '{"a":1}' and len(llm.sent) == 3
    assert r.cost_usd == pytest.approx(3 * 2000 / 1e9) and r.input_tokens == 30


def test_gives_up_with_empty_text_after_retries_rather_than_crashing():
    llm = make([resp(None)] * 5)
    assert llm.complete([{"role": "user", "content": "Q"}]).text == ""


def test_think_tags_are_stripped():
    assert make([resp("<think>hmm</think>\nfinal")]).complete([{"role": "user", "content": "Q"}]).text == "final"


def test_non_retryable_error_surfaces():
    with pytest.raises(RuntimeError, match="bad request"):
        make([ValueError("bad request")]).complete([{"role": "user", "content": "Q"}])
