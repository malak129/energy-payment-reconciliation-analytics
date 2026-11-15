"""Small shared presentation components; no financial business rules."""

from datetime import date
from decimal import Decimal
from math import ceil

import pandas as pd
import plotly.express as px
import streamlit as st

from energy_reconciliation.dashboard.analytics import paginate

PALETTE = ["#17324D", "#287C8E", "#8B9BAA", "#D7A34A"]


def euros(cents):
    value = f"{Decimal(cents) / 100:,.2f}"
    return value.replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def table(rows, *, columns=None):
    if not rows:
        st.info("No records match this selection.")
        return
    prepared = []
    for row in rows:
        current = {}
        for k, v in row.items():
            if columns and k not in columns:
                continue
            name = k.removesuffix("_cents").replace("_", " ").capitalize()
            if k.endswith("_cents"):
                name += " (EUR)"
                v = float(Decimal(v) / 100)
            elif isinstance(v, date):
                v = v.strftime("%d.%m.%Y")
            elif isinstance(v, (list, tuple)):
                v = ", ".join(map(str, v))
            current[name] = v
        prepared.append(current)
    frame = pd.DataFrame(prepared)
    config = {
        col: st.column_config.NumberColumn(format="€ %.2f")
        for col in frame.columns
        if col.endswith("(EUR)")
    }
    st.dataframe(frame, hide_index=True, column_config=config, width="stretch")


def paged_table(rows, key, columns=None):
    total_pages = max(1, ceil(len(rows) / 25))
    state_key = key + "_page"
    st.session_state[state_key] = min(max(1, st.session_state.get(state_key, 1)), total_pages)
    page = st.number_input("Page", min_value=1, max_value=total_pages, step=1, key=state_key)
    selected, total = paginate(rows, page, 25)
    st.caption(f"{total:,} records. Page {page} of {total_pages}. Up to 25 rows per page.")
    table(selected, columns=columns)
    return selected


def chart(rows, x, y, title, *, kind="line", money=True):
    if not rows:
        st.info(f"No data for {title.lower()}.")
        return
    frame = pd.DataFrame(rows)
    if money:
        frame[y] = frame[y].map(lambda n: float(Decimal(n) / 100))
    factory = px.bar if kind == "bar" else px.line
    figure = factory(
        frame,
        x=x,
        y=y,
        title=title,
        color_discrete_sequence=PALETTE,
        labels={
            x: x.replace("_", " ").capitalize(),
            y: "EUR" if money else y.replace("_", " ").capitalize(),
        },
    )
    figure.update_layout(
        template="plotly_white",
        font={"family": "Arial", "color": "#17324D"},
        margin={"l": 15, "r": 15, "t": 55, "b": 20},
        height=330,
    )
    if money:
        figure.update_yaxes(tickprefix="€ ", tickformat=",.0f", rangemode="tozero")
        figure.update_traces(hovertemplate="%{x}<br>€ %{y:,.2f}<extra></extra>")
    st.plotly_chart(figure, width="stretch")


def controls(report):
    failed = [r for r in report.checks if r["status"] != "PASS"]
    if failed:
        st.error(f"{len(failed)} financial controls FAIL. Differences are shown below.")
    else:
        st.success(
            f"Financial controls PASS — {len(report.checks)} exact-cent checks, zero differences."
        )


def period_picker(report, key):
    dates = [r["booked_on"] for r in report.tables["Payment Register"]]
    dates += [r["issued_on"] for r in report.tables["Invoice Register"]]
    first = min(dates) if dates else report.metadata["as_of"]
    return st.date_input(
        "Date range",
        value=(first, report.metadata["as_of"]),
        min_value=first,
        max_value=report.metadata["as_of"],
        key=key,
    )
