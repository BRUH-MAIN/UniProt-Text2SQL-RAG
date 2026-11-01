"""Execution-accuracy result comparison.

Two result sets are compared as multisets of rows, ignoring column order and
column names (a model may alias columns differently from the gold query).

  strict   - same number of columns, and the rows match once columns are aligned.
  relaxed  - the prediction may return *extra* columns (e.g. the protein name next
             to the accession that was asked for); the gold columns must still all
             be present with identical values.

`ordered=True` additionally requires the same row order (use only when the
question asks for a ranking).
"""
from collections import Counter
from decimal import Decimal
from typing import Any, Iterable, Sequence

Row = tuple


def norm_value(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 4)
    if isinstance(v, str):
        return " ".join(v.split())
    return str(v)


def norm_rows(rows: Iterable[Sequence[Any]]) -> list[Row]:
    return [tuple(norm_value(v) for v in r) for r in rows]


def _column_counters(rows: list[Row], ncols: int) -> list[Counter]:
    return [Counter(r[i] for r in rows) for i in range(ncols)]


def _numeric_key(row: Row):
    """Numeric cells of a row, or None if it has none (so it can never tie)."""
    nums = tuple(v for v in row if isinstance(v, float))
    return nums or None


def _tie_groups(gold: list[Row]) -> list[tuple[int, int]]:
    """Runs of consecutive gold rows with identical numeric cells (ties in a ranking).

    The question does not define the order inside a tie, so it is not scored.
    """
    groups, start = [], 0
    for i in range(1, len(gold) + 1):
        same = (i < len(gold) and _numeric_key(gold[i]) is not None
                and _numeric_key(gold[i]) == _numeric_key(gold[i - 1]))
        if not same:
            groups.append((start, i))
            start = i
    return groups


def _align(gold: list[Row], pred: list[Row], mapping: list[int], ordered: bool) -> bool:
    projected = [tuple(r[i] for i in mapping) for r in pred]
    if ordered:
        return all(Counter(projected[a:b]) == Counter(gold[a:b]) for a, b in _tie_groups(gold))
    return Counter(projected) == Counter(gold)


def _find_mapping(gold, pred, gcols, pcols, ordered, used=None, mapping=None, gcount=None, pcount=None):
    """Backtracking search for an injective gold-col -> pred-col mapping."""
    if gcount is None:
        gcount = _column_counters(gold, gcols)
        pcount = _column_counters(pred, pcols)
        used, mapping = set(), []
    j = len(mapping)
    if j == gcols:
        return _align(gold, pred, mapping, ordered)
    for i in range(pcols):
        if i in used or gcount[j] != pcount[i]:
            continue
        used.add(i)
        mapping.append(i)
        if _find_mapping(gold, pred, gcols, pcols, ordered, used, mapping, gcount, pcount):
            return True
        mapping.pop()
        used.discard(i)
    return False


def results_match(
    gold_rows: Sequence[Sequence[Any]],
    pred_rows: Sequence[Sequence[Any]],
    *,
    ordered: bool = False,
    relaxed: bool = False,
) -> bool:
    gold, pred = norm_rows(gold_rows), norm_rows(pred_rows)
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    gcols, pcols = len(gold[0]), len(pred[0])
    if pcols < gcols or (pcols != gcols and not relaxed):
        return False
    return _find_mapping(gold, pred, gcols, pcols, ordered)


def cell_f1(gold_rows, pred_rows) -> float:
    """Partial credit: F1 over the multiset of individual cell values."""
    g = Counter(v for r in norm_rows(gold_rows) for v in r)
    p = Counter(v for r in norm_rows(pred_rows) for v in r)
    if not g and not p:
        return 1.0
    overlap = sum((g & p).values())
    if overlap == 0:
        return 0.0
    prec, rec = overlap / sum(p.values()), overlap / sum(g.values())
    return 2 * prec * rec / (prec + rec)
