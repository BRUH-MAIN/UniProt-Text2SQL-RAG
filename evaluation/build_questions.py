"""Execute every gold query, validate it, and write the pinned benchmark artefacts.

  evaluation/questions.jsonl     questions + gold SQL + gold result fingerprint
  evaluation/gold_results.json   full gold result sets (used for answer-stage scoring)
  evaluation/data_snapshot.json  per-table row counts + content hash of the database

Validation rules (the build fails loudly rather than ship a bad benchmark):
  - gold SQL must execute without error
  - an 'rows' item returns <= 200 rows (the pipeline caps results at 200)
  - a ranking whose last two rows tie on every numeric column is flagged (unfair to score)
  - duplicate question ids / texts are rejected
"""
import hashlib
import json
import sys
from pathlib import Path

import psycopg

from evaluation.dbexec import READONLY_URL, execute, json_safe
from evaluation.questions_src import QUESTIONS

HERE = Path(__file__).parent
ROW_CAP = 200
# questions where an empty gold result is the intended answer
ALLOW_EMPTY = {"em01"}


def snapshot() -> dict:
    with psycopg.connect(READONLY_URL) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]
        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        digest = conn.execute(
            "SELECT md5(string_agg(entry || ':' || length(sequence) || ':' || coalesce(protein_names,''), ',' ORDER BY entry)) "
            "FROM proteins").fetchone()[0]
        version = conn.execute("SHOW server_version").fetchone()[0]
    return {"postgres": version, "row_counts": counts, "proteins_md5": digest}


def tie_at_boundary(sql: str, rows: list) -> bool:
    """For `... LIMIT k` rankings: does row k tie with row k+1 on all numeric columns?"""
    import re
    m = re.search(r"\bLIMIT\s+(\d+)\s*$", sql.strip(), re.I)
    if not m:
        return False
    k = int(m.group(1))
    if k <= 1 and "ORDER BY" not in sql.upper():
        return False
    bigger = execute(re.sub(r"\bLIMIT\s+\d+\s*$", f"LIMIT {k + 1}", sql.strip(), flags=re.I),
                     pipeline_limit=False)
    if not bigger.ok or len(bigger.rows) <= k:
        return False
    a, b = bigger.rows[k - 1], bigger.rows[k]
    nums = [i for i, v in enumerate(a) if isinstance(v, (int, float)) or hasattr(v, "as_tuple")]
    return bool(nums) and all(a[i] == b[i] for i in nums)


def main() -> int:
    ids, texts = set(), set()
    problems, out_q, gold = [], [], {}
    for qd in QUESTIONS:
        if qd["id"] in ids or qd["q"] in texts:
            problems.append(f"{qd['id']}: duplicate id or text")
        ids.add(qd["id"]); texts.add(qd["q"])
        rec = dict(qd)
        if qd["expect"] == "rows":
            r = execute(qd["sql"], pipeline_limit=False)
            if not r.ok:
                problems.append(f"{qd['id']}: gold SQL failed: {r.error}")
                continue
            if len(r.rows) > ROW_CAP:
                problems.append(f"{qd['id']}: gold returns {len(r.rows)} rows > {ROW_CAP}")
            if not r.rows and qd["id"] not in ALLOW_EMPTY:
                problems.append(f"{qd['id']}: gold returns no rows")
            if qd["ordered"] and tie_at_boundary(qd["sql"], r.rows):
                problems.append(f"{qd['id']}: ranking ties at the LIMIT boundary")
            blob = json.dumps([[json_safe(v) for v in row] for row in r.rows])
            rec["gold"] = {"columns": r.columns, "n_rows": len(r.rows),
                           "md5": hashlib.md5(blob.encode()).hexdigest()}
            gold[qd["id"]] = {"columns": r.columns, "rows": [[json_safe(v) for v in row] for row in r.rows]}
        out_q.append(rec)

    snap = snapshot()
    (HERE / "data_snapshot.json").write_text(json.dumps(snap, indent=2))
    if problems:
        print("BUILD FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    with open(HERE / "questions.jsonl", "w") as f:
        for rec in out_q:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (HERE / "gold_results.json").write_text(json.dumps(gold, ensure_ascii=False))
    by_cat: dict[str, int] = {}
    for rec in out_q:
        by_cat[rec["cat"]] = by_cat.get(rec["cat"], 0) + 1
    print(f"OK: {len(out_q)} questions  {by_cat}")
    print(f"snapshot: proteins={snap['row_counts']['proteins']} md5={snap['proteins_md5']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
