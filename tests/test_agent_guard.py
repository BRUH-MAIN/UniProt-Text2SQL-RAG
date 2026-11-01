import pytest

from agent.guard import check_sql, clean_sql
from evaluation.redteam import CASES

TABLES = {
    "proteins", "functions", "subcellular_locations", "disease_involvement", "biotechnological_uses",
    "pharmaceutical_uses", "toxic_doses", "allergenic_properties", "interactions", "taxonomic_lineage",
    "active_sites", "binding_sites", "mutagenesis", "topological_domains", "genes", "protein_genes",
    "pathways", "protein_pathways", "protein_families", "protein_family_memberships",
}

# Cases the guard must reject. The rest are legitimate SELECTs the guard allows; resource abuse
# (cartesian join, unbounded result) is contained by the executor, see test_agent_database.py.
MUST_BLOCK_CLASSES = {"write", "exfil"}
MUST_BLOCK_IDS = {"d_pg_sleep"}
MUST_ALLOW_IDS = {"ctl_select", "ctl_cte", "ctl_semicolon_in_literal", "d_cartesian",
                  "d_unbounded_comment", "d_unbounded_subquery_limit"}


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_redteam_case(case):
    cid, klass, _desc, sql, _expect = case
    res = check_sql(sql, TABLES)
    if klass in MUST_BLOCK_CLASSES or cid in MUST_BLOCK_IDS:
        assert not res.ok, f"{cid} should be blocked"
        assert res.reason
    else:
        assert cid in MUST_ALLOW_IDS, f"classify {cid}"
        assert res.ok, f"{cid} should be allowed: {res.reason}"


def test_fences_and_semicolon_are_cleaned():
    assert clean_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert check_sql("```sql\nSELECT entry FROM proteins;\n```", TABLES).ok


def test_unknown_table_message_lists_available_tables():
    res = check_sql("SELECT * FROM protien", TABLES)
    assert not res.ok and "proteins" in res.reason


def test_cte_may_shadow_and_be_referenced():
    assert check_sql("WITH t AS (SELECT entry FROM proteins) SELECT * FROM t", TABLES).ok


def test_schema_qualified_public_ok_others_rejected():
    assert check_sql("SELECT entry FROM public.proteins", TABLES).ok
    assert not check_sql("SELECT * FROM pg_catalog.pg_user", TABLES).ok
    assert not check_sql("SELECT * FROM information_schema.tables", TABLES).ok


def test_prose_is_rejected_not_crashed():
    res = check_sql("I'm sorry, I can't do that.", TABLES)
    assert not res.ok


def test_oversize_rejected():
    assert not check_sql("SELECT " + "1," * 4000 + "1", TABLES).ok
