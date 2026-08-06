"""Streamlit read-only research report viewer."""

from __future__ import annotations

import streamlit as st

from apps.web.client import ReportWebClientError, fetch_report, fetch_task_status
from src.core import load_settings


def main() -> None:
    """Render one report returned by the public FastAPI boundary."""

    settings = load_settings()
    st.set_page_config(page_title="DeepInsight Reports", layout="wide")
    st.title("DeepInsight Research Reports")
    st.caption("Phase One read-only report browser")
    job_id = st.text_input("Job ID")
    if st.button("Check job status") and job_id.strip():
        try:
            task = fetch_task_status(
                settings.web.api_base_url,
                job_id,
                timeout_seconds=settings.web.request_timeout_seconds,
            )
        except ReportWebClientError as exc:
            st.error(str(exc))
        else:
            st.json(task)
    report_id = st.text_input("Report ID")
    if not st.button("Load report") or not report_id.strip():
        return
    try:
        report = fetch_report(
            settings.web.api_base_url,
            report_id,
            timeout_seconds=settings.web.request_timeout_seconds,
        )
    except ReportWebClientError as exc:
        st.error(str(exc))
        return
    st.subheader(str(report.get("title") or report_id))
    st.caption(
        f"Status: {report.get('status')} · "
        f"Asset: {report.get('asset_id')} · "
        f"Date: {report.get('report_date')}"
    )
    markdown = report.get("report_markdown")
    if isinstance(markdown, str):
        st.markdown(markdown)
    with st.expander("Structured JSON"):
        st.json(report)


main()
