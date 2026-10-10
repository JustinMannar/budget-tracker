"""Analytics: recurring-charge detection (SQL) and anomaly detection (pandas)."""
import re
import sqlite3

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- recurring

_NOISE = re.compile(r"[#*]?\d+|[^A-Z ]")


def normalize_merchant(description: str) -> str:
    """'NETFLIX.COM #123' -> 'NETFLIX COM'. Strips store numbers and punctuation."""
    cleaned = _NOISE.sub(" ", description.upper())
    return " ".join(cleaned.split())


# Cadence buckets: (label, min_avg_gap_days, max_avg_gap_days, max_gap_stddev_days)
CADENCES = [
    ("weekly", 6, 8, 1.5),
    ("semi-monthly", 13, 17, 2.5),
    ("monthly", 27, 34, 4.0),
    ("quarterly", 85, 97, 7.0),
    ("annual", 355, 375, 10.0),
]

# Variance is compared to tolerance**2 so SQLite needs no SQRT function.
_RECURRING_SQL = """
WITH tx AS (
    SELECT date, norm_merchant(description) AS merchant, -amount AS cost
    FROM transactions
    WHERE amount < 0
),
gaps AS (
    SELECT merchant, date, cost,
           julianday(date)
             - julianday(LAG(date) OVER (PARTITION BY merchant ORDER BY date)) AS gap
    FROM tx
)
SELECT merchant,
       COUNT(*)                                       AS charges,
       AVG(cost)                                      AS avg_cost,
       AVG(cost * cost) - AVG(cost) * AVG(cost)       AS cost_var,
       AVG(gap)                                       AS avg_gap,
       AVG(gap * gap) - AVG(gap) * AVG(gap)           AS gap_var,
       MIN(date)                                      AS first_seen,
       MAX(date)                                      AS last_seen
FROM gaps
GROUP BY merchant
HAVING COUNT(*) >= :min_charges
"""


def _classify(avg_gap: float, gap_var: float) -> str | None:
    for label, lo, hi, max_sd in CADENCES:
        if lo <= avg_gap <= hi and gap_var <= max_sd**2:
            return label
    return None


def detect_recurring(
    conn: sqlite3.Connection,
    min_charges: int = 3,
    max_amount_variation: float = 0.10,
) -> pd.DataFrame:
    """Find subscriptions/bills: steady cadence and (nearly) constant amount.

    Window function LAG() gives the days between consecutive charges per
    merchant; the cadence must fit a known bucket with low spread, and the
    charge amount's std-dev must be within `max_amount_variation` of its mean.
    """
    conn.create_function("norm_merchant", 1, normalize_merchant, deterministic=True)
    rows = conn.execute(_RECURRING_SQL, {"min_charges": min_charges}).fetchall()

    out = []
    for r in rows:
        if r["avg_cost"] <= 0 or r["cost_var"] > (max_amount_variation * r["avg_cost"]) ** 2:
            continue
        cadence = _classify(r["avg_gap"], r["gap_var"])
        if cadence is None:
            continue
        out.append({
            "merchant": r["merchant"],
            "cadence": cadence,
            "charges": r["charges"],
            "avg_cost": round(r["avg_cost"], 2),
            "monthly_cost": round(r["avg_cost"] * 30.44 / r["avg_gap"], 2),
            "last_seen": r["last_seen"],
            "next_expected": (
                pd.Timestamp(r["last_seen"]) + pd.Timedelta(days=round(r["avg_gap"]))
            ).strftime("%Y-%m-%d"),
        })
    cols = ["merchant", "cadence", "charges", "avg_cost", "monthly_cost",
            "last_seen", "next_expected"]
    return (pd.DataFrame(out, columns=cols)
            .sort_values("monthly_cost", ascending=False, ignore_index=True))


# ---------------------------------------------------------------- anomalies

MAD_TO_SIGMA = 0.6745       # makes modified z comparable to a normal z-score
MEANAD_TO_SIGMA = 1.2533    # fallback scale when MAD is 0 (many identical values)


def _robust_scores(spent: pd.Series) -> tuple[pd.Series, float] | None:
    """Modified z-score of each value vs the group's median, or None if no spread."""
    med = spent.median()
    dev = spent.sub(med).abs()
    scale = dev.median() / MAD_TO_SIGMA
    if scale == 0:  # >50% identical values: fall back to mean abs deviation
        scale = dev.mean() * MEANAD_TO_SIGMA
    if scale == 0:
        return None
    return (spent - med) / scale, med


def detect_anomalies(
    df: pd.DataFrame,
    threshold: float = 3.5,
    min_history: int = 6,
) -> pd.DataFrame:
    """Flag unusually large/small spending.

    Each charge is compared to the merchant's own history when the merchant
    has at least `min_history` charges (so a $30 pizza isn't "high" just because
    Dining also contains $8 burritos); otherwise to its category. Scoring is a
    robust median/MAD modified z-score, so a few big outliers don't inflate
    the scale the way a mean/std z-score would. Expects columns date,
    description, amount, category; only spending (amount < 0) is scored.
    """
    spend = df[df["amount"] < 0].copy()
    spend = spend[~spend["category"].isin(["Income", "Uncategorized"])]
    spend["spent"] = -spend["amount"]
    spend["merchant"] = spend["description"].map(normalize_merchant)

    has_history = spend.groupby("merchant")["spent"].transform("size") >= min_history
    passes = [
        (spend[has_history], "merchant", "this merchant's usual"),
        (spend[~has_history], "category", "typical"),
    ]

    flagged = []
    for part, key, label in passes:
        for _, g in part.groupby(key):
            if len(g) < min_history:
                continue
            scored = _robust_scores(g["spent"])
            if scored is None:
                continue
            score, med = scored
            g = g.assign(score=score, median=med, label=label)
            flagged.append(g[g["score"].abs() > threshold])

    cols = ["date", "description", "category", "spent", "median", "score", "reason"]
    if not flagged:
        return pd.DataFrame(columns=cols)
    res = pd.concat(flagged)
    direction = np.where(res["score"] > 0, "higher", "lower")
    res["reason"] = "Much " + pd.Series(direction, index=res.index) + " than " + res["label"]
    return (res[cols].sort_values("score", key=np.abs, ascending=False,
                                  ignore_index=True).round(2))
