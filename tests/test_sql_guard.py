from baseline.sql_guard import clean_sql, is_safe_select


def test_clean_sql_strips_markdown_fences():
    assert clean_sql("```sql\nSELECT 1;\n```") == "SELECT 1;"
    assert clean_sql("```\nSELECT 1;\n```") == "SELECT 1;"
    assert clean_sql("SELECT 1;") == "SELECT 1;"


def test_plain_select_is_safe():
    assert is_safe_select("SELECT * FROM proteins") is True


def test_select_with_trailing_semicolon_is_safe():
    assert is_safe_select("SELECT * FROM proteins;") is True


def test_cte_select_is_safe():
    sql = "WITH x AS (SELECT protein_id FROM proteins) SELECT * FROM x"
    assert is_safe_select(sql) is True


def test_drop_table_is_rejected():
    assert is_safe_select("DROP TABLE proteins;") is False


def test_delete_is_rejected():
    assert is_safe_select("DELETE FROM proteins WHERE protein_id = 1;") is False


def test_update_is_rejected():
    assert is_safe_select("UPDATE proteins SET sequence = '' WHERE protein_id = 1;") is False


def test_stacked_statements_are_rejected():
    assert is_safe_select("SELECT 1; DROP TABLE proteins;") is False


def test_insert_is_rejected():
    assert is_safe_select("INSERT INTO proteins (entry) VALUES ('X')") is False
