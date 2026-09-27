import sqlite3

from jarvis_pi.memory.temporal import layer_sql_filter


def test_hot_layer_sql() -> None:
    sql, params = layer_sql_filter("hot", "f.created_at", hot_hours=3, warm_days=7)
    assert "datetime('now', ?)" in sql
    assert params == ("-3 hours",)


def test_warm_layer_sql() -> None:
    sql, params = layer_sql_filter("warm", "f.created_at", hot_hours=3, warm_days=7)
    assert params == ("-3 hours", "-7 days")


def test_cold_layer_sql() -> None:
    sql, params = layer_sql_filter("cold", "f.created_at", hot_hours=3, warm_days=7)
    assert params == ("-7 days",)


def test_all_layer_empty() -> None:
    sql, params = layer_sql_filter("all", "f.created_at", hot_hours=3, warm_days=7)
    assert sql == ""
    assert params == ()


def test_hot_filter_in_sqlite() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE facts (id INTEGER, created_at TEXT)")
    conn.execute(
        "INSERT INTO facts VALUES (1, datetime('now', '-1 hours'))"
    )
    conn.execute(
        "INSERT INTO facts VALUES (2, datetime('now', '-10 hours'))"
    )
    layer_sql, layer_params = layer_sql_filter("hot", "created_at", hot_hours=3, warm_days=7)
    rows = conn.execute(
        f"SELECT id FROM facts WHERE 1=1 {layer_sql}",
        layer_params,
    ).fetchall()
    assert [r[0] for r in rows] == [1]
