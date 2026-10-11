import numpy as np
import pandas as pd
import pytest

import forecast


def tx(rows):
    return pd.DataFrame(rows, columns=["date", "amount", "category"])


# ---------------------------------------------------------------- data prep

def test_partial_trailing_month_is_dropped():
    df = tx([("2026-01-10", -100, "Dining"), ("2026-02-10", -100, "Dining"),
             ("2026-03-05", -999, "Dining")])  # March only observed through the 5th
    s = forecast.monthly_spending(df)
    assert [str(p) for p in s.index] == ["2026-01", "2026-02"]


def test_complete_last_month_is_kept():
    df = tx([("2026-01-10", -100, "Dining"), ("2026-02-28", -100, "Dining")])
    assert len(forecast.monthly_spending(df)) == 2


def test_gap_months_become_zero_and_income_is_excluded():
    df = tx([("2026-01-10", -100, "Dining"), ("2026-01-11", 5000, "Income"),
             ("2026-03-10", -50, "Dining"), ("2026-03-31", -1, "Dining")])
    s = forecast.monthly_spending(df)
    assert list(s.values) == [100.0, 0.0, 51.0]


def test_by_category_pivots():
    df = tx([("2026-01-10", -10, "Dining"), ("2026-01-11", -20, "Coffee"),
             ("2026-02-28", -5, "Dining")])
    p = forecast.monthly_spending(df, by_category=True)
    assert p.loc[pd.Period("2026-01"), "Coffee"] == 20
    assert p.loc[pd.Period("2026-02"), "Coffee"] == 0


# ------------------------------------------------------------------- models

def test_models_on_constant_series_predict_the_constant():
    y = np.full(8, 250.0)
    for name, model in forecast.MODELS.items():
        assert model(y) == pytest.approx(250.0), name


def test_linear_trend_extrapolates():
    y = np.array([100.0, 110, 120, 130, 140])
    assert forecast.linear_trend(y) == pytest.approx(150.0)


def test_linear_trend_never_negative():
    assert forecast.linear_trend(np.array([30.0, 20, 10, 1])) >= 0


# ----------------------------------------------------------------- backtest

def test_backtest_has_no_lookahead():
    """Predictions for month t must be identical if every later month is changed."""
    y = np.array([100.0, 120, 90, 110, 130, 105, 115])
    base = forecast.backtest(y)
    tampered = y.copy()
    tampered[5:] = 9999
    changed = forecast.backtest(tampered)
    # errors for t=3 and t=4 depend only on y[:t] and y[t]; compare predictions
    for name in forecast.MODELS:
        pred_base = [y[t] - base[name][t - 3] for t in (3, 4)]
        pred_changed = [tampered[t] - changed[name][t - 3] for t in (3, 4)]
        assert pred_base == pytest.approx(pred_changed), name


def test_backtest_count():
    errs = forecast.backtest(np.arange(10.0))
    assert all(len(e) == 7 for e in errs.values())


def test_trend_model_wins_on_trending_data():
    y = pd.Series(np.arange(100.0, 100 + 10 * 9, 10))   # perfectly linear growth
    res = forecast.run_forecast(y)
    assert res.model in ("linear trend",)
    assert res.forecast == pytest.approx(y.iloc[-1] + 10)
    assert res.table.set_index("model").loc["linear trend", "MAE"] == pytest.approx(0, abs=1e-6)
    assert res.table.set_index("model").loc[forecast.BASELINE, "MAE"] == pytest.approx(10)


def test_mean_beats_naive_on_noisy_flat_data():
    y = pd.Series([200.0, 260, 150, 240, 170, 250, 160, 245, 175, 255])
    res = forecast.run_forecast(y)
    t = res.table.set_index("model")
    assert t.loc["historical mean", "MAE"] < t.loc[forecast.BASELINE, "MAE"]
    assert t.loc[res.model, "vs naive %"] > 0


def test_baseline_has_zero_skill_against_itself():
    res = forecast.run_forecast(pd.Series([100.0, 150, 120, 180, 140, 160]))
    assert res.table.set_index("model").loc[forecast.BASELINE, "vs naive %"] == pytest.approx(0)


def test_too_little_history_returns_none():
    assert forecast.run_forecast(pd.Series([100.0, 120, 110])) is None


def test_interval_brackets_forecast_and_flags_low_confidence():
    res = forecast.run_forecast(pd.Series([100.0, 140, 90, 130, 95, 135]))
    assert 0 <= res.lower <= res.forecast <= res.upper
    assert res.low_confidence            # only 3 backtest points
    assert res.n_backtest == 3
