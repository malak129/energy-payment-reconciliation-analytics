"""Local Streamlit entry point. Launch with streamlit run, never a public deployment."""

import argparse
import os
from pathlib import Path

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from energy_reconciliation.dashboard import queries
from energy_reconciliation.dashboard.pages import PAGES, RENDERERS


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--database", default=os.environ.get("ENERGY_RECONCILIATION_DB", "data/phase4-demo.sqlite3")
    )
    parser.add_argument(
        "--exports", default=os.environ.get("ENERGY_RECONCILIATION_EXPORTS", "outputs/dashboard")
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=os.environ.get("ENERGY_RECONCILIATION_READ_ONLY") == "1",
    )
    args, _ = parser.parse_known_args()
    st.set_page_config(page_title="Energy Financial Operations", page_icon=None, layout="wide")
    st.markdown(
        """<style>
      .stApp {background:#f7f9fc;color:#17324d;}
      [data-testid="stSidebar"] {background:#edf2f7;}
      [data-testid="stMetric"] {background:white;border:1px solid #dce3eb;
        border-radius:8px;padding:16px;margin-bottom:12px;}
      .block-container {padding-top:4rem;padding-bottom:2rem;max-width:1600px;}
      h1,h2,h3 {color:#17324d;}
    </style>""",
        unsafe_allow_html=True,
    )
    st.info("SYNTHETIC DATA — PORTFOLIO DEMONSTRATION")
    st.sidebar.title("Financial Operations")
    path = st.sidebar.text_input("Local SQLite database", args.database, key="database_path")
    st.sidebar.caption(
        "Fictional energy utility. Local demonstration actors are labels, not authentication."
    )
    if st.sidebar.button("Refresh database"):
        queries.invalidate()
        st.rerun()
    page = st.sidebar.radio("Navigation", PAGES, key="navigation")
    st.title(page)
    try:
        catalog = queries.catalog(path)
        if not catalog["datasets"]:
            st.warning(
                "Database is initialized but contains no dataset. Import synthetic data "
                "and persist reconciliation first."
            )
            return
        dataset = st.sidebar.selectbox("Dataset", catalog["datasets"], key="dataset")
        head = catalog["heads"].get(dataset)
        if head is None:
            st.warning(
                "Dataset imported but not reconciled. Persist reconciliation with the CLI first."
            )
            return
        runs = [r for r in catalog["runs"] if r["dataset_id"] == dataset]
        dates = ["Any persisted date"] + sorted({r["as_of"] for r in runs})
        if st.session_state.get("snapshot_date") not in dates:
            st.session_state["snapshot_date"] = dates[0]
        chosen_date = st.sidebar.selectbox("Persisted as-of date", dates, key="snapshot_date")
        by_id = {r["id"]: r for r in runs}
        choices = [r["id"] for r in runs if chosen_date == dates[0] or r["as_of"] == chosen_date]
        if chosen_date == dates[0] or by_id[head["run_id"]]["as_of"] == chosen_date:
            choices.insert(0, "Current accepted ledger")
        if st.session_state.get("snapshot_run") not in choices:
            st.session_state["snapshot_run"] = choices[0]
        selected = st.sidebar.selectbox(
            "Persisted run",
            choices,
            key="snapshot_run",
            format_func=lambda value: (
                value
                if value == "Current accepted ledger"
                else f"{by_id[value]['as_of']} · {by_id[value]['kind']} · {value[-10:]}"
            ),
        )
        run_id = head["run_id"] if selected == "Current accepted ledger" else selected
        with st.spinner("Loading persisted financial snapshot…"):
            report = queries.snapshot(path, dataset, run_id)
        st.caption(
            f"Business as-of {report.metadata['as_of']:%d.%m.%Y}. Knowledge cutoff "
            f"UTC {report.metadata['known_at_utc']}."
        )
        with st.expander("Snapshot identity and financial definitions"):
            st.json(report.metadata)
            st.write(
                "Reconciliation rate = net allocated / adjusted receivables. Monthly "
                "activity is distinct from cumulative closing balances. No real company "
                "affiliation."
            )
        context = dict(
            path=Path(path),
            exports=Path(args.exports),
            catalog=catalog,
            read_only=args.read_only,
            current=run_id == head["run_id"],
        )
        RENDERERS[page](report, context)
    except (OSError, ValueError, SQLAlchemyError) as exc:
        st.error(f"Unable to complete this view: {exc}")
        st.caption(
            "Use an existing initialized synthetic database with a completed "
            "reconciliation run. Refresh after another local writer changes state."
        )


if __name__ == "__main__":
    main()
