"""Generate 24 months of realistic fake transactions into sample_transactions.csv."""
import random
from datetime import date
from pathlib import Path

import pandas as pd

random.seed(42)
OUT = Path(__file__).parent / "sample_transactions.csv"

# (description, low, high, per-month frequency)
SPENDING = [
    ("KROGER #482", 25, 120, 6), ("TRADER JOE'S", 20, 80, 3),
    ("WHOLE FOODS MKT", 30, 110, 2), ("CHIPOTLE ONLINE", 10, 18, 4),
    ("PIZZA HUT", 15, 35, 2), ("TACO BELL", 6, 14, 3),
    ("STARBUCKS STORE 1123", 4, 9, 9), ("DUNKIN", 3, 7, 4),
    ("UBER *TRIP", 8, 35, 5), ("SHELL OIL 5521", 25, 55, 3),
    ("AMAZON.COM*2K4", 10, 90, 5), ("TARGET 0042", 15, 100, 3),
    ("CVS PHARMACY", 8, 40, 1), ("AMC THEATRES", 12, 30, 1),
    ("STEAM PURCHASE", 10, 60, 1), ("RANDOM CORNER SHOP", 5, 40, 2),
]
MONTHLY_FIXED = [
    ("OAKWOOD APARTMENTS RENT", -1350, 1), ("CITY ELECTRIC CO", -95, 5),
    ("NETFLIX.COM", -15.49, 8), ("SPOTIFY USA", -11.99, 12),
    ("COMCAST INTERNET", -69.99, 18),
]


def main(months: int = 24) -> None:
    rows = []
    this_month = pd.Period(date.today(), freq="M")
    for m in range(months):
        period = this_month - m
        first = period.start_time.date()
        age = months - 1 - m                      # 0 = oldest month
        inflation = 1 + 0.004 * age               # prices creep up ~0.4%/month
        holiday = 1.6 if period.month == 12 else 1.0
        for desc, amt, day in MONTHLY_FIXED:
            rows.append((first.replace(day=day), desc, amt))
        for pay_day in (1, 15):
            rows.append((first.replace(day=pay_day), "ACME CORP PAYROLL", 2150.00))
        for desc, lo, hi, freq in SPENDING:
            bump = holiday if desc.startswith(("AMAZON", "TARGET")) else 1.0
            for _ in range(random.randint(max(freq - 1, 0), freq + 1)):
                d = first.replace(day=random.randint(1, 28))
                amount = random.uniform(lo, hi) * inflation * bump
                rows.append((d, desc, -round(amount, 2)))
    df = pd.DataFrame(rows, columns=["date", "description", "amount"])
    df = df[df["date"] <= date.today()].sort_values("date")
    df.to_csv(OUT, index=False)
    print(f"Wrote {len(df)} transactions to {OUT.name}")


if __name__ == "__main__":
    main()
