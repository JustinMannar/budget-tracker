import io

import pytest

import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


def category_of(conn, description):
    return conn.execute(
        "SELECT name FROM categories WHERE id = ?", (db.categorize(conn, description),)
    ).fetchone()["name"]


def test_categorize_known_merchant_is_case_insensitive(conn):
    assert category_of(conn, "STARBUCKS STORE 1123") == "Coffee"
    assert category_of(conn, "Netflix.com") == "Subscriptions"


def test_categorize_unknown_falls_back(conn):
    assert category_of(conn, "RANDOM CORNER SHOP") == "Uncategorized"


def test_import_is_idempotent(conn):
    csv = "date,description,amount\n2026-01-05,KROGER #1,-40.10\n2026-01-06,ACME PAYROLL,2000\n"
    assert db.import_csv(conn, io.StringIO(csv)) == (2, 0)
    assert db.import_csv(conn, io.StringIO(csv)) == (0, 2)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_import_rejects_missing_columns(conn):
    with pytest.raises(ValueError, match="missing columns"):
        db.import_csv(conn, io.StringIO("date,amount\n2026-01-01,5\n"))


def test_recategorize_after_adding_rule(conn):
    db.import_csv(conn, io.StringIO("date,description,amount\n2026-01-05,JOES BAKERY,-9\n"))
    assert category_of(conn, "JOES BAKERY") == "Uncategorized"
    conn.execute(
        "INSERT INTO rules (pattern, category_id) "
        "SELECT 'bakery', id FROM categories WHERE name = 'Dining'"
    )
    assert db.recategorize_uncategorized(conn) == 1
