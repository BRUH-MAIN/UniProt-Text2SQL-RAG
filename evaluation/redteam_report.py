"""Render evaluation/results/redteam.md from the legacy and hardened red-team runs."""
import json
from pathlib import Path

R = Path(__file__).parent / "results"


def main() -> None:
    legacy = {r["id"]: r for r in json.loads((R / "redteam_legacy.json").read_text())}
    hard = {r["id"]: r for r in json.loads((R / "redteam_hardened.json").read_text())}
    lines = [
        "| case | what it does | legacy guard | legacy: SELECT-only role | legacy: privileged role | hardened (any role) |",
        "|---|---|---|---|---|---|",
    ]
    for cid, l in legacy.items():
        h = hard[cid]
        verdict = "passes" if l["guard_passed"] else "**blocks**"
        hardened = h["readonly_summary"] if h["readonly_summary"] == h["privileged_summary"] else \
            f"{h['readonly_summary']} / {h['privileged_summary']}"
        lines.append(f"| `{cid}` | {l['desc']} | {verdict} | {l['readonly_summary']} | {l['privileged_summary']} | {hardened} |")

    def hostile(rs):  # everything that is not a control
        return [r for r in rs.values() if r["class"] != "control"]

    n = len(hostile(legacy))
    passed = sum(bool(r["guard_passed"]) for r in hostile(legacy))
    harmful_priv = sum(1 for r in hostile(legacy)
                       if r["privileged_summary"].startswith(("ran", "EXECUTED", "RAN")))
    harmful_priv_h = sum(1 for r in hostile(hard)
                         if r["privileged_summary"].startswith(("ran", "EXECUTED", "RAN"))
                         and r["class"] in ("write", "exfil"))
    lines += ["", f"Hostile cases: {n}. Legacy guard let {passed} of them through to the database. "
              f"Run as a privileged role, {harmful_priv} of the hostile cases did something unwanted "
              f"(executed a write, read a file, hung, or returned an unbounded result) under the legacy path; "
              f"under the hardened path {harmful_priv_h} write/exfiltration cases ran.", ""]
    (R / "redteam.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
