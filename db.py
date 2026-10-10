"""SQLite data layer: schema, categorization rules, CSV import."""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DB_PATH = ROOT / "budget.db"

DEFAULT_CATEGORIES = {
    "Groceries": 400, "Dining": 150, "Coffee": 40, "Transport": 120,
    "Rent": 1400, "Utilities": 200, "Subscriptions": 60,
    "Entertainment": 100, "Shopping": 150, "Health": 80,
    "Income": None, "Uncategorized": None,
}

DEFAULT_RULES = {
    "kroger": "Groceries", "trader joe": "Groceries", "whole foods": "Groceries",
    "aldi": "Groceries", "chipotle": "Dining", "mcdonald": "Dining",
    "pizza": "Dining", "taco": "Dining", "starbucks": "Coffee",
    "dunkin": "Coffee", "uber": "Transport", "lyft": "Transport",
    "shell": "Transport", "bp ": "Transport", "apartments": "Rent",
    "electric": "Utilities", "water": "Utilities", "internet": "Utilities",
    "netflix": "Subscriptions", "spotify": "Subscriptions",
    "hulu": "Subscriptions", "amc": "Entertainment", "steam": "Entertainment",
    "amazon": "Shopping", "target": "Shopping", "cvs": "Health",
    "payroll": "Income", "direct deposit": "Income",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript((ROOT / "schema.sql").read_text())
    for name, budget in DEFAULT_CATEGORIES.items():
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, budget) VALUES (?, ?)",
            (name, budget),
        )
    for pattern, cat in DEFAULT_RULES.items():
        conn.execute(
            "INSERT OR IGNORE INTO rules (pattern, category_id) "
            "SELECT ?, id FROM categories WHERE name = ?",
            (pattern, cat),
        )
    conn.commit()


def categorize(conn: sqlite3.Connection, description: str) -> int:
    """Return category id for a description using the first matching rule."""
    desc = description.lower()
    for row in conn.execute("SELECT pattern, category_id FROM rules"):
        if row["pattern"] in desc:
            return row["category_id"]
    return conn.execute(
        "SELECT id FROM categories WHERE name = 'Uncategorized'"
    ).fetchone()["id"]


def import_csv(conn: sqlite3.Connection, source) -> tuple[int, int]:
    """Import a CSV with columns date, description, amount.

    Returns (inserted, skipped_duplicates).
    """
    df = pd.read_csv(source)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"date", "description", "amount"} - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    inserted = 0
    for r in df.itertuples():
        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions "
            "(date, description, amount, category_id) VALUES (?, ?, ?, ?)",
            (r.date, str(r.description), float(r.amount),
             categorize(conn, str(r.description))),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted, len(df) - inserted


def recategorize_uncategorized(conn: sqlite3.Connection) -> int:
    """Re-run rules over Uncategorized transactions (after adding rules)."""
    unc = conn.execute(
        "SELECT id FROM categories WHERE name = 'Uncategorized'"
    ).fetchone()["id"]
    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE category_id = ?", (unc,)
    ).fetchall()
    changed = 0
    for r in rows:
        new = categorize(conn, r["description"])
        if new != unc:
            conn.execute(
                "UPDATE transactions SET category_id = ? WHERE id = ?", (new, r["id"])
            )
            changed += 1
    conn.commit()
    return changed
