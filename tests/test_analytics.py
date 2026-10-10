import pandas as pd
import pytest

import analytics
import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


def add(conn, date, description, amount):
    conn.execute(
        "INSERT INTO transactions (date, description, amount, category_id) VALUES (?,?,?,1)",
        (date, description, amount),
    )


def test_normalize_merchant():
    assert analytics.normalize_merchant("NETFLIX.COM #123") == "NETFLIX COM"
    assert analytics.normalize_merchant("Starbucks Store 1123") == "STARBUCKS STORE"


def test_detects_monthly_subscription(conn):
    for m in range(1, 7):
        add(conn, f"2026-{m:02d}-08", "NETFLIX.COM", -15.49)
    res = analytics.detect_recurring(conn)
    assert list(res["merchant"]) == ["NETFLIX COM"]
    row = res.iloc[0]
    assert row["cadence"] == "monthly"
    assert row["avg_cost"] == 15.49
    assert row["next_expected"].startswith("2026-07")


def test_detects_weekly_charge(conn):
    for d in pd.date_range("2026-01-05", periods=8, freq="7D"):
        add(conn, d.strftime("%Y-%m-%d"), "GYM CLASS PASS", -12.00)
    assert analytics.detect_recurring(conn).iloc[0]["cadence"] == "weekly"


def test_ignores_variable_amounts(conn):
    for m, amt in enumerate([20, 95, 41, 180, 33, 77], start=1):
        add(conn, f"2026-{m:02d}-10", "KROGER", -amt)
    assert analytics.detect_recurring(conn).empty


def test_ignores_irregular_timing(conn):
    for d in ["2026-01-02", "2026-01-09", "2026-03-30", "2026-04-02", "2026-06-20"]:
        add(conn, d, "ODD SHOP", -10.00)
    assert analytics.detect_recurring(conn).empty


def test_requires_min_charges(conn):
    add(conn, "2026-01-08", "NEW SUB", -9.99)
    add(conn, "2026-02-08", "NEW SUB", -9.99)
    assert analytics.detect_recurring(conn).empty


def _spend(amounts, category="Dining"):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(amounts)),
        "description": [f"M{i}" for i in range(len(amounts))],
        "amount": [-a for a in amounts],
        "category": category,
    })


def test_flags_obvious_outlier():
    res = analytics.detect_anomalies(_spend([12, 14, 11, 13, 15, 12, 14, 13, 12, 250]))
    assert list(res["spent"]) == [250.0]
    assert "higher" in res.iloc[0]["reason"]


def test_no_flags_for_normal_spending():
    assert analytics.detect_anomalies(_spend([12, 14, 11, 13, 15, 12, 14, 13, 12, 16])).empty


def test_skips_small_categories():
    assert analytics.detect_anomalies(_spend([10, 10, 500])).empty


def test_identical_values_use_fallback_scale():
    # rent-like: mostly identical, one change must still be caught
    res = analytics.detect_anomalies(_spend([1350] * 9 + [1900], category="Rent"))
    assert list(res["spent"]) == [1900.0]


def test_expensive_merchant_not_flagged_against_cheap_category_peers():
    """Regression: $30 pizza orders are normal for the pizza place, not 'anomalies'."""
    cheap = pd.DataFrame({
        "description": "TACO BELL",
        "amount": [-8.0, -9, -7, -8, -9, -7, -8, -9, -7, -8],
    })
    pricey = pd.DataFrame({
        "description": "PIZZA HUT",
        "amount": [-30.0, -28, -32, -29, -31, -30, -27, -33],
    })
    df = pd.concat([cheap, pricey], ignore_index=True)
    df["date"] = pd.date_range("2026-01-01", periods=len(df))
    df["category"] = "Dining"
    assert analytics.detect_anomalies(df).empty


def test_outlier_vs_own_merchant_history_is_flagged():
    rows = [-30.0, -28, -32, -29, -31, -30, -27, -120]
    df = pd.DataFrame({"description": "PIZZA HUT", "amount": rows, "category": "Dining",
                       "date": pd.date_range("2026-01-01", periods=len(rows))})
    res = analytics.detect_anomalies(df)
    assert list(res["spent"]) == [120.0]
    assert "this merchant" in res.iloc[0]["reason"]


def test_income_never_flagged():
    df = _spend([10] * 9 + [9999], category="Income")
    assert analytics.detect_anomalies(df).empty
