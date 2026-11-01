"""Deterministic check that an answer is supported by the query result.

An LLM-written summary can state numbers or accessions that are not in the rows it was
shown. This catches that without a second model: every number and UniProt accession
mentioned in the answer must appear in the evidence (every result the agent obtained, or the
question itself), and an answer to an empty result must say that nothing was found.

Deliberately conservative: a number the model *derived* (e.g. 12000 - 11597 = 403) is flagged
even when it is right, because it cannot be verified from the rows.
"""
import re
from dataclasses import dataclass, field

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
_ACCESSION = re.compile(r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})\b")
# "1." / "2)" / "(3)" at the start of a line are list numbering, not claims about the data
_ENUMERATOR = re.compile(r"^[ \t]*\(?\d{1,2}[.)]", re.MULTILINE)
_NONE = re.compile(r"\b(no|none|not|nothing|zero|n/?a|cannot|can't|isn't|aren't|doesn't|does not|unavailable)\b", re.I)


@dataclass
class Grounding:
    ungrounded_numbers: list[str] = field(default_factory=list)
    ungrounded_accessions: list[str] = field(default_factory=list)
    empty_result_not_acknowledged: bool = False

    @property
    def ok(self) -> bool:
        return not (self.ungrounded_numbers or self.ungrounded_accessions or self.empty_result_not_acknowledged)

    def describe(self) -> str:
        parts = []
        if self.ungrounded_numbers:
            parts.append("numbers not found in the result: " + ", ".join(self.ungrounded_numbers))
        if self.ungrounded_accessions:
            parts.append("accessions not found in the result: " + ", ".join(self.ungrounded_accessions))
        if self.empty_result_not_acknowledged:
            parts.append("the query returned nothing but the answer does not say so")
        return "; ".join(parts)


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    return s[:-2] if s.endswith(".0") else s


def _numbers_in(text: str, *, is_answer: bool = False) -> set[str]:
    if is_answer:  # list numbering only exists in the model's prose, never in the evidence
        text = _ENUMERATOR.sub("", text)
    return {_norm_num(m) for m in _NUM.findall(text)}


def check_grounding(answer: str, question: str, rows: list[tuple], truncated: bool = False) -> Grounding:
    g = Grounding()
    if not rows:
        g.empty_result_not_acknowledged = not _NONE.search(answer or "")
        return g
    haystack = " ".join(str(c) for r in rows for c in r)
    # whole-number floats render as 12000.0 in rows but are written 12000 in prose
    allowed = _numbers_in(haystack) | _numbers_in(question) | {str(len(rows))}
    for n in _numbers_in(answer, is_answer=True):
        if n not in allowed and not (truncated and n == "200"):
            g.ungrounded_numbers.append(n)
    seen = set(_ACCESSION.findall(haystack)) | set(_ACCESSION.findall(question))
    g.ungrounded_accessions = sorted(set(_ACCESSION.findall(answer)) - seen)
    return g
