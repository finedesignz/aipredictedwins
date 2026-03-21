"""
Streamlit monitoring dashboard for the Kalshi prediction market trading bot.
Reads from SQLite database at data/trades.db.

Run with: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Ensure imports work from the dashboard/ directory
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3

import pandas as pd
import streamlit as st

DB_PATH = PROJECT_ROOT / "data" / "trades.db"

st.set_page_config(
    page_title="AI Predicted Wins - Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("AI Predicted Wins - Trading Dashboard")


def get_connection() -> sqlite3.Connection | None:
    """Return a SQLite connection if the database exists, else None."""
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(str(DB_PATH))


def load_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    """Load an entire table into a DataFrame, returning empty DF on error."""
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)  # noqa: S608
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
conn = get_connection()

if conn is None:
    st.info("No database found yet. Start the trading bot to generate data.")
    st.stop()

trades_df = load_table(conn, "trades")
daily_df = load_table(conn, "daily_stats")
sims_df = load_table(conn, "simulations")
conn.close()

if trades_df.empty:
    st.info("No trades recorded yet. The dashboard will populate once the bot places its first trade.")
    st.stop()

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
resolved_df = trades_df[trades_df["status"].isin(["won", "lost"])]
open_df = trades_df[trades_df["status"] == "open"]

total_pnl = resolved_df["pnl"].sum() if not resolved_df.empty else 0.0
bankroll = 1000.0 + total_pnl
wins = len(resolved_df[resolved_df["status"] == "won"])
losses = len(resolved_df[resolved_df["status"] == "lost"])
resolved_count = wins + losses
win_rate = (wins / resolved_count * 100) if resolved_count > 0 else 0.0
open_count = len(open_df)

# ---------------------------------------------------------------------------
# 1. Portfolio Overview
# ---------------------------------------------------------------------------
st.header("Portfolio Overview")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Bankroll", f"${bankroll:,.2f}")
col2.metric("Total P&L", f"${total_pnl:,.2f}", delta=f"${total_pnl:,.2f}")
col3.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{wins}W / {losses}L")
col4.metric("Open Positions", open_count)

st.divider()

# ---------------------------------------------------------------------------
# 2. Trade Log Table
# ---------------------------------------------------------------------------
st.header("Trade Log")

display_df = trades_df.sort_values("timestamp", ascending=False).copy()

# Truncate long event titles for readability
if "event_title" in display_df.columns:
    display_df["event_title"] = display_df["event_title"].astype(str).str[:60]

trade_columns = [
    "kalshi_ticker",
    "event_title",
    "side",
    "contracts",
    "entry_price_cents",
    "mirofish_prob",
    "kalshi_price_at_entry",
    "gap",
    "pnl",
    "status",
    "timestamp",
]
# Only keep columns that actually exist in the data
trade_columns = [c for c in trade_columns if c in display_df.columns]


def color_status(val: str) -> str:
    """Return CSS color string based on trade status."""
    colors = {
        "won": "background-color: #1b5e20; color: white",
        "lost": "background-color: #b71c1c; color: white",
        "open": "background-color: #f9a825; color: black",
        "sold": "background-color: #37474f; color: white",
    }
    return colors.get(str(val).lower(), "")


styled = display_df[trade_columns].style.applymap(
    color_status, subset=["status"] if "status" in trade_columns else []
)
st.dataframe(styled, use_container_width=True, height=400)

st.divider()

# ---------------------------------------------------------------------------
# 3. P&L Curve
# ---------------------------------------------------------------------------
st.header("Cumulative P&L")

if not resolved_df.empty:
    pnl_series = (
        resolved_df.sort_values("timestamp")[["timestamp", "pnl"]]
        .copy()
        .reset_index(drop=True)
    )
    pnl_series["cumulative_pnl"] = pnl_series["pnl"].cumsum()
    pnl_series["timestamp"] = pd.to_datetime(pnl_series["timestamp"], errors="coerce")
    pnl_series = pnl_series.set_index("timestamp")

    st.line_chart(pnl_series["cumulative_pnl"])
else:
    st.info("No resolved trades yet to plot P&L curve.")

st.divider()

# ---------------------------------------------------------------------------
# 4. Accuracy Over Time (Rolling 20-trade win rate)
# ---------------------------------------------------------------------------
st.header("Accuracy Over Time (Rolling 20-Trade Win Rate)")

if resolved_count >= 2:
    accuracy_df = resolved_df.sort_values("timestamp").copy().reset_index(drop=True)
    accuracy_df["is_win"] = (accuracy_df["status"] == "won").astype(int)
    window = min(20, resolved_count)
    accuracy_df["rolling_win_rate"] = (
        accuracy_df["is_win"].rolling(window=window, min_periods=1).mean() * 100
    )
    accuracy_df["timestamp"] = pd.to_datetime(accuracy_df["timestamp"], errors="coerce")
    accuracy_df = accuracy_df.set_index("timestamp")

    st.line_chart(accuracy_df["rolling_win_rate"])
else:
    st.info("Need at least 2 resolved trades to display accuracy over time.")

st.divider()

# ---------------------------------------------------------------------------
# 5. Gap Distribution (histogram colored by outcome)
# ---------------------------------------------------------------------------
st.header("Gap Distribution by Outcome")

if not resolved_df.empty and "gap" in resolved_df.columns:
    gap_df = resolved_df[["gap", "status"]].copy()
    won_gaps = gap_df[gap_df["status"] == "won"]["gap"]
    lost_gaps = gap_df[gap_df["status"] == "lost"]["gap"]

    chart_data = pd.DataFrame(
        {
            "Won": won_gaps.values if not won_gaps.empty else [],
            "Lost": lost_gaps.values if not lost_gaps.empty else [],
        }
    )

    # Build a histogram using pandas cut, then bar chart
    import numpy as np

    all_gaps = gap_df["gap"].dropna()
    if not all_gaps.empty:
        bin_edges = np.linspace(all_gaps.min(), all_gaps.max(), 15)
        won_hist = pd.cut(won_gaps.dropna(), bins=bin_edges).value_counts().sort_index()
        lost_hist = pd.cut(lost_gaps.dropna(), bins=bin_edges).value_counts().sort_index()

        hist_df = pd.DataFrame({"Won": won_hist.values, "Lost": lost_hist.values})
        hist_df.index = [f"{iv.left:.2f}-{iv.right:.2f}" for iv in won_hist.index]

        st.bar_chart(hist_df)
    else:
        st.info("No gap data available.")
else:
    st.info("No resolved trades with gap data to display.")

st.divider()

# ---------------------------------------------------------------------------
# 6. Recent Simulations
# ---------------------------------------------------------------------------
st.header("Recent Simulations")

if not sims_df.empty:
    sims_display = sims_df.sort_values("timestamp", ascending=False).head(20).copy()

    if "event_title" in sims_display.columns:
        sims_display["event_title"] = sims_display["event_title"].astype(str).str[:60]

    if "traded" in sims_display.columns:
        sims_display["traded"] = sims_display["traded"].apply(
            lambda x: "Yes" if x else "No"
        )

    sim_columns = [
        "kalshi_ticker",
        "event_title",
        "mirofish_prob",
        "kalshi_price_at_sim",
        "gap",
        "traded",
        "timestamp",
    ]
    sim_columns = [c for c in sim_columns if c in sims_display.columns]

    st.dataframe(sims_display[sim_columns], use_container_width=True, height=400)
else:
    st.info("No simulations recorded yet.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption("AI Predicted Wins - Kalshi Trading Bot Dashboard")
