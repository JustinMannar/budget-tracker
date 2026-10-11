"""Streamlit budget dashboard. Run: streamlit run app.py"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analytics
import db
import forecast

st.set_page_config(page_title="Budget Tracker", layout="wide")

conn = db.connect()
db.init_db(conn)

QUERY = """
SELECT t.id, t.date, t.description, t.amount, c.name AS category, c.budget
FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
"""


@st.cache_data(ttl=5)
def load() -> pd.DataFrame:
    df = pd.read_sql_query(QUERY, db.connect())
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)
    return df


# ---- Sidebar: import ----
st.sidebar.header("Import transactions")
upload = st.sidebar.file_uploader("CSV (date, description, amount)", type="csv")
if upload and st.sidebar.button("Import"):
    try:
        ins, skip = db.import_csv(conn, upload)
        st.sidebar.success(f"Imported {ins}, skipped {skip} duplicates")
        load.clear()
    except Exception as e:
        st.sidebar.error(str(e))

if st.sidebar.button("Load sample data"):
    ins, skip = db.import_csv(conn, db.ROOT / "sample_transactions.csv")
    st.sidebar.success(f"Imported {ins}, skipped {skip} duplicates")
    load.clear()

df = load()
st.title("Budget Tracker")
if df.empty:
    st.info("No data yet. Upload a CSV or click **Load sample data** in the sidebar.")
    st.stop()

months = sorted(df["month"].unique(), reverse=True)
month = st.sidebar.selectbox("Month", months)

spend = df[(df["amount"] < 0) & (df["category"] != "Income")].copy()
spend["spent"] = -spend["amount"]
cur = spend[spend["month"] == month]
income = df[(df["month"] == month) & (df["amount"] > 0)]["amount"].sum()

# ---- KPIs ----
c1, c2, c3 = st.columns(3)
c1.metric("Income", f"${income:,.0f}")
c2.metric("Spending", f"${cur['spent'].sum():,.0f}")
c3.metric("Net", f"${income - cur['spent'].sum():,.0f}")

tab1, tab2, tab3, tab4, tab5, tab7, tab6 = st.tabs(
    ["Overview", "Budget vs actual", "Merchants", "Recurring", "Anomalies", "Forecast",
     "Transactions"]
)

with tab1:
    left, right = st.columns(2)
    by_cat = cur.groupby("category", as_index=False)["spent"].sum()
    left.plotly_chart(
        px.pie(by_cat, names="category", values="spent", hole=0.45,
               title=f"Spending by category, {month}"),
        use_container_width=True,
    )
    trend = spend.groupby("month", as_index=False)["spent"].sum()
    right.plotly_chart(
        px.bar(trend, x="month", y="spent", title="Monthly spending"),
        use_container_width=True,
    )
    cat_trend = spend.groupby(["month", "category"], as_index=False)["spent"].sum()
    st.plotly_chart(
        px.line(cat_trend, x="month", y="spent", color="category", markers=True,
                title="Category trends"),
        use_container_width=True,
    )

with tab2:
    bva = cur.groupby(["category", "budget"], as_index=False, dropna=False)["spent"].sum()
    bva = bva.dropna(subset=["budget"])
    bva["pct"] = (bva["spent"] / bva["budget"] * 100).round(0)
    bva["status"] = bva["pct"].apply(lambda p: "Over" if p > 100 else "OK")
    fig = px.bar(bva, y="category", x="pct", color="status", orientation="h",
                 color_discrete_map={"Over": "#d62728", "OK": "#2ca02c"},
                 title="% of monthly budget used")
    fig.add_vline(x=100, line_dash="dash")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(bva[["category", "budget", "spent", "pct"]], hide_index=True)

with tab3:
    top = (cur.groupby("description", as_index=False)["spent"].sum()
           .nlargest(10, "spent"))
    st.plotly_chart(
        px.bar(top, x="spent", y="description", orientation="h",
               title=f"Top merchants, {month}")
        .update_yaxes(categoryorder="total ascending"),
        use_container_width=True,
    )

with tab4:
    rec = analytics.detect_recurring(conn)
    if rec.empty:
        st.info("No recurring charges detected yet (needs 3+ steady charges).")
    else:
        r1, r2 = st.columns(2)
        r1.metric("Recurring charges found", len(rec))
        r2.metric("Committed per month", f"${rec['monthly_cost'].sum():,.2f}")
        st.dataframe(rec, hide_index=True, use_container_width=True)

with tab5:
    sens = st.slider("Sensitivity (lower = flags more)", 2.5, 6.0, 3.5, 0.5)
    anom = analytics.detect_anomalies(df, threshold=sens)
    if anom.empty:
        st.success("No unusual transactions at this sensitivity.")
    else:
        st.caption(f"{len(anom)} unusual transactions, largest deviation first")
        st.dataframe(anom, hide_index=True, use_container_width=True)

with tab7:
    hist = forecast.monthly_spending(df)
    res = forecast.run_forecast(hist)
    if res is None:
        st.info("Need at least 4 complete months of history to forecast.")
    else:
        next_month = hist.index[-1] + 1
        f1, f2, f3 = st.columns(3)
        f1.metric(f"Forecast for {next_month}", f"${res.forecast:,.0f}")
        f2.metric("80% range", f"${res.lower:,.0f} – ${res.upper:,.0f}")
        best = res.table.iloc[0]
        f3.metric("Beats 'same as last month' by", f"{best['vs naive %']:.0f}%")
        if res.low_confidence:
            st.warning(f"Only {res.n_backtest} backtest months: treat this as a rough guess.")
        st.caption(f"Best model in backtest: **{res.model}** "
                   f"(scored on {res.n_backtest} months it had never seen)")

        fig = go.Figure()
        x_hist = [str(p) for p in hist.index]
        fig.add_scatter(x=x_hist, y=hist.values, mode="lines+markers", name="Actual")
        fig.add_scatter(
            x=[str(next_month)], y=[res.forecast], mode="markers", name="Forecast",
            marker=dict(size=12, color="#d62728"),
            error_y=dict(type="data", symmetric=False,
                         array=[res.upper - res.forecast],
                         arrayminus=[res.forecast - res.lower]),
        )
        fig.update_layout(title="Monthly spending and next-month forecast",
                          yaxis_title="Spending ($)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("How each model did in the backtest")
        st.dataframe(res.table.round(1), hide_index=True, use_container_width=True)
        st.caption("MAE = average dollars off. 'vs naive' = how much smaller the error is "
                   "than just guessing last month's number. Negative means worse.")

        st.subheader("By category")
        by_cat = forecast.monthly_spending(df, by_category=True)
        rows = []
        for cat in by_cat.columns:
            r = forecast.run_forecast(by_cat[cat])
            if r is not None and by_cat[cat].sum() > 0:
                rows.append({"category": cat, "forecast": round(r.forecast, 0),
                             "model": r.model, "vs naive %": round(r.table.iloc[0]["vs naive %"])})
        st.dataframe(pd.DataFrame(rows).sort_values("forecast", ascending=False),
                     hide_index=True, use_container_width=True)

with tab6:
    unc = df[df["category"] == "Uncategorized"]
    if not unc.empty:
        st.warning(f"{len(unc)} uncategorized transactions")
    st.dataframe(
        df[df["month"] == month].sort_values("date", ascending=False)
          [["date", "description", "amount", "category"]],
        hide_index=True, use_container_width=True,
    )
