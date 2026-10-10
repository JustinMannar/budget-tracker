# Budget Tracker

Python + SQLite + Streamlit expense tracker.

## Setup
```
pip install -r requirements.txt
python make_fake_data.py      # creates sample_transactions.csv
streamlit run app.py
```
Then click **Load sample data** in the sidebar (or upload your own CSV with
columns `date, description, amount`; negative = spending).

## Files
- `schema.sql` – tables
- `db.py` – DB init, rule-based categorization, CSV import (idempotent)
- `make_fake_data.py` – fake data generator
- `app.py` – dashboard
