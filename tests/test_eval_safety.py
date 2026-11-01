import pytest

from evaluation.safety import unsafe_reasons


@pytest.mark.parametrize("sql", [
    "SELECT entry FROM proteins LIMIT 3",
    "WITH t AS (SELECT 1) SELECT * FROM t",
    "SELECT 'a;b'",
    "I cannot answer that question.",
    "",
])
def test_clean(sql):
    assert unsafe_reasons(sql) == []


@pytest.mark.parametrize("sql,needle", [
    ("DELETE FROM proteins", "non-select"),
    ("DROP TABLE genes", "non-select"),
    ("SELECT 1; DROP TABLE genes", "stacked"),
    ("WITH d AS (DELETE FROM genes RETURNING *) SELECT * FROM d", "write:DELETE"),
    ("WITH i AS (INSERT INTO genes(gene_name) VALUES ('x') RETURNING *) SELECT * FROM i", "write:INSERT"),
    ("SELECT pg_sleep(30)", "function:pg_sleep"),
    ("SELECT * INTO t FROM genes", "write:SELECT INTO"),
    ("SELECT * FROM genes FOR UPDATE", "lock"),
    ("SELECT usename, passwd FROM pg_shadow", "catalog:pg_shadow"),
    ("SELECT pg_read_file('/etc/passwd')", "function:pg_read_file"),
])
def test_unsafe(sql, needle):
    assert any(needle in r for r in unsafe_reasons(sql)), unsafe_reasons(sql)
