"""Security/correctness regression tests for the finance assistant backend.
Run with: .\\.venv\\Scripts\\python.exe -m pytest
"""
import pandas as pd
import pytest

from backend.schema_introspect import is_query_safe
from backend import confidence


@pytest.mark.parametrize("tenant_id,valid", [
    ("default", True),
    ("my-tenant_1", True),
    ("../../etc/passwd", False),
    ("a" * 100, False),
    ("bad;chars", False),
])
def test_tenant_id_validation(tenant_id, valid):
    from backend.config import tenant_db_path
    if valid:
        tenant_db_path(tenant_id)  # should not raise
    else:
        with pytest.raises(ValueError):
            tenant_db_path(tenant_id)


@pytest.mark.parametrize("sql,expected_safe", [
    ("SELECT SUM(amount) FROM transactions", True),
    ("SELECT * FROM transactions WHERE vendor_id IN (SELECT vendor_id FROM vendor_payouts)", True),
    ("SELECT * FROM transactions; DROP TABLE transactions;", False),
    ("DROP TABLE transactions", False),
    ("ATTACH DATABASE 'x.db' AS x", False),
    ("PRAGMA table_info(transactions)", False),
    ("SELECT * FROM nonexistent_table", False),
    ("INSERT INTO transactions VALUES (1,2,3)", False),
    ("SELECT * FROM transactions UNION SELECT * FROM sqlite_master", False),
])
def test_sql_safety(sql, expected_safe, test_tenant_db):
    safe, _ = is_query_safe(sql, test_tenant_db)
    assert safe is expected_safe


def test_anomaly_detection_flags_outlier():
    df = pd.DataFrame({
        "vendor_id": [1, 2, 3, 4, 5],
        "amount": [500, 480, 520, 510, 9800],
    })
    anomalies = confidence.detect_anomalies(df, group_col="vendor_id", value_col="amount")
    assert len(anomalies) == 1
    assert anomalies[0]["direction"] == "unusually high"


def test_empty_result_detected():
    df = pd.DataFrame({"total": pd.array([float("nan")], dtype="float64")})
    assert confidence.is_effectively_empty(df) is True


def test_non_empty_result_not_flagged():
    df = pd.DataFrame({"total": [123.45]})
    assert confidence.is_effectively_empty(df) is False


def test_tenant_data_isolation(test_tenant_db):
    """A query against one tenant must never see another tenant's tables."""
    from backend.query_engine import QueryError, run_query

    # The pytest tenant has 'transactions'; a fresh, unrelated tenant does not.
    other_tenant = "other_tenant_no_data"
    with pytest.raises(QueryError):
        run_query("SELECT * FROM transactions", other_tenant)

    # But the real test tenant can query its own table fine.
    df = run_query("SELECT SUM(amount) AS total FROM transactions", test_tenant_db)
    assert df.iloc[0]["total"] == 600.0


def test_session_memory_persists_and_is_tenant_scoped():
    from backend import memory

    memory.reset_session("s1", tenant_id="tenant_a")
    memory.reset_session("s1", tenant_id="tenant_b")

    memory.append_turn("s1", "How much did we spend?", "SELECT 1", "42", tenant_id="tenant_a")
    memory.append_turn("s1", "Different tenant question", "SELECT 2", "99", tenant_id="tenant_b")

    history_a = memory.get_history("s1", tenant_id="tenant_a")
    history_b = memory.get_history("s1", tenant_id="tenant_b")

    assert len(history_a) == 1 and history_a[0]["answer"] == "42"
    assert len(history_b) == 1 and history_b[0]["answer"] == "99"

