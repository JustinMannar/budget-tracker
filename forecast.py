"""Monthly spending forecasts, always judged against a naive baseline via backtesting."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_TRAIN = 3          # months of history needed before the first backtest prediction
Z_80 = 1.2816          # z for a two-sided 80% interval


# ------------------------------------------------------------------ data prep

def monthly_spending(
    df: pd.DataFrame,
    as_of: pd.Timestamp | None = None,
    by_category: bool = False,
) -> pd.Series | pd.DataFrame:
    """Total spending per calendar month (positive numbers), complete months only.

    A trailing month is dropped if `as_of` (default: latest transaction date) falls
    before its last day, since a half-finished month would look like a spending drop.
    Months with no spending are kept as 0 so gaps don't silently shorten the series.
    """
    d = df[(df["amount"] < 0) & (df["category"] != "Income")].copy()
    d["spent"] = -d["amount"]
    d["month"] = pd.to_datetime(d["date"]).dt.to_period("M")
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.to_datetime(df["date"]).max()

    if by_category:
        out = d.pivot_table(index="month", columns="category", values="spent",
                            aggfunc="sum", fill_value=0.0)
    else:
        out = d.groupby("month")["spent"].sum()
    if out.empty:
        return out
    out = out.reindex(pd.period_range(out.index.min(), out.index.max(), freq="M"),
                      fill_value=0.0)
    if as_of < out.index[-1].end_time.normalize():
        out = out.iloc[:-1]
    return out


# ---------------------------------------------------------------------- models
# Each model maps a history array to a one-step-ahead prediction.

def naive(y: np.ndarray) -> float:
    return float(y[-1])


def historical_mean(y: np.ndarray) -> float:
    return float(y.mean())


def moving_average_3(y: np.ndarray) -> float:
    return float(y[-3:].mean())


def linear_trend(y: np.ndarray) -> float:
    window = y[-6:]
    if len(window) < 3:
        return float(y[-1])
    x = np.arange(len(window))
    slope, intercept = np.polyfit(x, window, 1)
    return float(max(0.0, slope * len(window) + intercept))


def exp_smoothing(y: np.ndarray) -> float:
    """Simple exponential smoothing; alpha chosen by in-sample one-step error."""
    def run(alpha: float) -> tuple[float, float]:
        level, sse = y[0], 0.0
        for v in y[1:]:
            sse += (v - level) ** 2
            level = alpha * v + (1 - alpha) * level
        return sse, level

    if len(y) < 2:
        return float(y[-1])
    return float(min((run(a) for a in np.arange(0.1, 1.0, 0.1)), key=lambda r: r[0])[1])


MODELS = {
    "naive (last month)": naive,
    "historical mean": historical_mean,
    "3-month average": moving_average_3,
    "linear trend": linear_trend,
    "exp. smoothing": exp_smoothing,
}
BASELINE = "naive (last month)"


# -------------------------------------------------------------------- backtest

def backtest(y: np.ndarray, min_train: int = MIN_TRAIN) -> dict[str, np.ndarray]:
    """Expanding-window one-step-ahead errors (actual - predicted) for each model.

    For month t the model only sees y[:t], so there is no look-ahead leakage.
    """
    errors: dict[str, list[float]] = {name: [] for name in MODELS}
    for t in range(min_train, len(y)):
        for name, model in MODELS.items():
            errors[name].append(float(y[t] - model(y[:t])))
    return {k: np.array(v) for k, v in errors.items()}


def _metrics(y: np.ndarray, errors: dict[str, np.ndarray], min_train: int) -> pd.DataFrame:
    actual = y[min_train:]
    rows = []
    for name, e in errors.items():
        nz = actual != 0
        rows.append({
            "model": name,
            "MAE": float(np.abs(e).mean()),
            "MAPE %": float((np.abs(e[nz]) / actual[nz]).mean() * 100) if nz.any() else np.nan,
        })
    t = pd.DataFrame(rows)
    base = t.loc[t["model"] == BASELINE, "MAE"].iloc[0]
    t["vs naive %"] = (1 - t["MAE"] / base) * 100 if base > 0 else 0.0
    return t.sort_values("MAE", ignore_index=True)


@dataclass
class ForecastResult:
    model: str
    forecast: float
    lower: float
    upper: float
    table: pd.DataFrame        # backtest metrics per model, best first
    n_backtest: int            # number of out-of-sample months scored
    low_confidence: bool       # True when the backtest has too few points to trust


def run_forecast(y: pd.Series, min_train: int = MIN_TRAIN) -> ForecastResult | None:
    """Pick the model with the best backtest MAE and forecast the next month."""
    values = np.asarray(y, dtype=float)
    if len(values) < min_train + 1:
        return None
    errors = backtest(values, min_train)
    table = _metrics(values, errors, min_train)
    best = table.iloc[0]["model"]
    point = MODELS[best](values)

    e = errors[best]
    sd = float(e.std(ddof=1)) if len(e) > 1 else 0.0
    return ForecastResult(
        model=best,
        forecast=point,
        lower=max(0.0, point - Z_80 * sd),
        upper=point + Z_80 * sd,
        table=table,
        n_backtest=len(e),
        low_confidence=len(e) < 6,
    )
