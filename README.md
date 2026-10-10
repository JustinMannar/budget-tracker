# Budget Tracker

[![CI](https://github.com/JustinMannar/budget-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/JustinMannar/budget-tracker/actions/workflows/ci.yml)

Personal finance analytics built with Python, SQLite, and Streamlit.

## Features
- **CSV import** (`date, description, amount`), idempotent: re-importing never duplicates.
- **Rule-based categorization** with per-category monthly budgets.
- **Dashboard**: spending by category, trends, budget vs actual, top merchants.
- **Recurring-charge detection** in SQL: `LAG()` window function computes the gap between
  consecutive charges per merchant; a charge counts as recurring when its cadence fits
  weekly / semi-monthly / monthly / quarterly / annual with low spread *and* its amount is
  nearly constant. Reports monthly committed cost and next expected date.
- **Anomaly detection**: robust (median/MAD) modified z-scores, computed against the
  merchant's own history when available and the category otherwise.

## Design notes
- *Why median/MAD?* A plain mean/std z-score is inflated by the very outliers it tries to
  find. MAD is robust to them. When over half the values are identical (e.g. rent), MAD is 0,
  so the scale falls back to mean absolute deviation.
- *Why per-merchant scoring?* The first version scored against the whole category and flagged
  8 ordinary $30 pizza orders as anomalies (category median was dragged down by $8 tacos).
  Comparing a merchant to itself removed these false positives; a regression test covers it.
- SQLite lacks `SQRT`, so SQL compares variance to `tolerance²` instead of std-dev to tolerance.

## Setup
```
pip install -r requirements.txt
python make_fake_data.py      # creates sample_transactions.csv
streamlit run app.py
```
Click **Load sample data** in the sidebar, or upload your own CSV (negative = spending).

## Development
```
pip install -r requirements-dev.txt
pytest
ruff check .
```

## Layout
- `schema.sql`, `db.py` – tables, categorization, import
- `analytics.py` – recurring + anomaly detection
- `app.py` – Streamlit dashboard
- `make_fake_data.py` – fake data generator
- `tests/` – pytest suite (run in CI on every push)

## Roadmap
Forecasting with backtests vs. a naive baseline, ML categorization, safe "ask your data"
natural-language queries, Docker, and a hosted demo.
