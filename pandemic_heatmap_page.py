"""
pandemic_heatmap_page.py  ─  Medi‑Flow Orchestrator  ─  Consultation‑Based Pandemic Heatmap

Interactive Streamlit page linked directly to consultation records:
  • Severity-weighted heatmap of consultation-linked visits
  • AI-predicted outbreak hotspot clusters (DBSCAN)
  • Anomaly / spike detection alerts
  • Trend-over-time chart with date slider
  • Diagnosis-type filter (preset + custom)
  • Medicine allocation recommendations
  • Visit recording form for doctors

Entry point: render()
"""

from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

from heatmap_service import (
    generate_ai_pandemic_heatmap,
    analyse_trends,
    SEVERITY_WEIGHT,
)

# ── Backend config ───────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"

# Common diagnosis types for quick filter
_DIAGNOSIS_OPTIONS = [
    "",
    "fever",
    "cough",
    "influenza",
    "respiratory infection",
    "covid-19",
    "dengue",
    "pneumonia",
    "diarrhoea",
    "headache",
    "sore throat",
    "skin rash",
    "allergy",
]


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ═════════════════════════════════════════════════════════════
#  Data fetching
# ═════════════════════════════════════════════════════════════

def _fetch_visits(start_date: str, end_date: str, diagnosis: str = "") -> list:
    """Fetch consultation-linked visits from the backend API."""
    params = {"start_date": start_date, "end_date": end_date}
    if diagnosis:
        params["diagnosis"] = diagnosis
    try:
        resp = requests.get(
            f"{API_BASE}/api/visits",
            params=params,
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []




# ═════════════════════════════════════════════════════════════
#  Main entry point
# ═════════════════════════════════════════════════════════════

def render():
    st.title("🌡️ Consultation-Based Pandemic Heatmap")
    st.caption(
        "Directly linked to doctor consultation records.  "
        "Identify outbreak hotspots, track trends, predict risk areas, "
        "and receive AI-powered medicine allocation recommendations."
    )

    # ── Tab layout ─────────────────────────────────────────────
    tab_map, tab_trend = st.tabs([
        "🗺️ Heatmap Dashboard",
        "📈 Trend Analysis",
    ])

    with tab_map:
        _render_heatmap_dashboard()

    with tab_trend:
        _render_trend_analysis()


# ═════════════════════════════════════════════════════════════
#  Heatmap Dashboard
# ═════════════════════════════════════════════════════════════

def _render_heatmap_dashboard():
    # ── Filters ──────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🔍 Consultation Filters")
        c1, c2 = st.columns(2)

        with c1:
            start_date = st.date_input(
                "Start Date",
                value=date.today() - timedelta(days=30),
                key="hm_start",
            )
        with c2:
            end_date = st.date_input(
                "End Date",
                value=date.today(),
                key="hm_end",
            )

        c3, c4 = st.columns(2)
        with c3:
            diag_select = st.selectbox(
                "Diagnosis Type",
                _DIAGNOSIS_OPTIONS,
                format_func=lambda x: "All Diagnoses" if x == "" else x.title(),
                key="hm_diag_select",
            )
        with c4:
            custom_diag = st.text_input(
                "Custom Diagnosis Filter",
                placeholder="Type to search …",
                key="hm_diag_custom",
            )

    diagnosis_filter = custom_diag.strip() or diag_select

    # ── Fetch data and generate heatmap ──────────────────────
    if st.button("🗺️ Generate Consultation Heatmap", type="primary", use_container_width=True, key="hm_generate"):
        with st.spinner("Fetching consultation records and running AI analysis …"):
            visits = _fetch_visits(
                start_date.isoformat(),
                end_date.isoformat(),
                diagnosis_filter,
            )

            if not visits:
                st.warning(
                    "No consultation records found for the selected filters. "
                    "Consultations are auto-linked when a doctor confirms AI analysis."
                )
                return

            # Run the AI pipeline
            heatmap, geo_df, med_recs, alerts, trend_df = generate_ai_pandemic_heatmap(visits)

            # Store results in session state for display
            st.session_state["hm_results"] = {
                "heatmap": heatmap,
                "geo_df": geo_df,
                "med_recs": med_recs,
                "alerts": alerts,
                "trend_df": trend_df,
                "total_visits": len(visits),
                "geocoded": len(geo_df) if not geo_df.empty else 0,
            }

    # ── Display results (persisted in session state) ─────────
    results = st.session_state.get("hm_results")
    if not results:
        st.info("Set date range and click **Generate Heatmap** to start.")
        return

    heatmap = results["heatmap"]
    geo_df = results["geo_df"]
    med_recs = results["med_recs"]
    alerts = results["alerts"]

    # ── Summary metrics ──────────────────────────────────────
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Consultations", results["total_visits"])
        m2.metric("📍 Geocoded", results["geocoded"])

        if not geo_df.empty and "predicted_risk" in geo_df.columns:
            high_count = len(geo_df[geo_df["predicted_risk"] == "HIGH"])
            anomaly_count = len(geo_df[geo_df["predicted_risk"] == "ANOMALY"])
        else:
            high_count = 0
            anomaly_count = 0

        m3.metric("🔴 High-Risk Cases", high_count)
        m4.metric("⚠️ Anomalies", anomaly_count)

    # ── Anomaly alerts ───────────────────────────────────────
    if alerts:
        with st.container(border=True):
            st.markdown("#### ⚠️ Anomaly Alerts — Sudden Spikes Detected")
            for alert in alerts:
                st.error(
                    f"**{alert['severity']}** in Cluster {alert['cluster']} "
                    f"— {alert['recent_cases']} cases in last 7 days "
                    f"(vs {alert['prior_cases']} prior). "
                    f"Top diagnosis: **{alert['top_diagnosis']}**"
                )

    # ── Interactive heatmap ──────────────────────────────────
    if heatmap:
        with st.container(border=True):
            st.markdown("#### 🗺️ Consultation-Based Severity Heatmap")
            st.caption(
                "Directly linked to doctor consultation records. "
                "Intensity reflects severity weight (low=1, medium=2, high=3). "
                "Click cluster markers for detailed info."
            )
            st_folium(heatmap, width=None, height=500, returned_objects=[])
    else:
        st.warning("Could not geocode any patient addresses for the map.")

    # ── Diagnosis distribution ───────────────────────────────
    if not geo_df.empty:
        with st.container(border=True):
            st.markdown("#### 📊 Diagnosis Distribution")
            c1, c2 = st.columns(2)

            with c1:
                # Diagnosis counts
                diag_counts = geo_df["diagnosis"].value_counts().reset_index()
                diag_counts.columns = ["Diagnosis", "Cases"]
                st.dataframe(diag_counts, use_container_width=True, hide_index=True)

            with c2:
                # Severity breakdown
                sev_counts = geo_df["severity"].value_counts().reset_index()
                sev_counts.columns = ["Severity", "Cases"]
                st.dataframe(sev_counts, use_container_width=True, hide_index=True)

    # ── Cluster details ──────────────────────────────────────
    if not geo_df.empty and "cluster" in geo_df.columns:
        clustered = geo_df[geo_df["cluster"] >= 0]
        if not clustered.empty:
            with st.container(border=True):
                st.markdown("#### 🎯 Predicted Hotspot Clusters")
                cluster_summary = []
                for cid, group in clustered.groupby("cluster"):
                    risk = group["predicted_risk"].mode().iloc[0]
                    risk_icon = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟢"}.get(risk, "⚪")
                    top_diag = group["diagnosis"].value_counts().head(1)
                    cluster_summary.append({
                        "Cluster": int(cid),
                        "Cases": len(group),
                        "Avg Severity": f"{group['weight'].mean():.1f}",
                        "Risk": f"{risk_icon} {risk}",
                        "Top Diagnosis": top_diag.index[0] if not top_diag.empty else "-",
                    })
                st.dataframe(
                    pd.DataFrame(cluster_summary),
                    use_container_width=True,
                    hide_index=True,
                )

    # ── Medicine allocation recommendations ──────────────────
    if not med_recs.empty:
        with st.container(border=True):
            st.markdown("#### 💊 Medicine / Resource Allocation Recommendations")
            st.caption(
                "Estimated based on diagnosis distribution and severity weighting. "
                "Units = severity_weight × 5 per case."
            )
            st.dataframe(med_recs, use_container_width=True, hide_index=True)

    # ── Raw visit data (expandable) ──────────────────────────
    if not geo_df.empty:
        with st.expander("📋 View Raw Consultation Data"):
            display_cols = [
                "patient_name", "home_address", "diagnosis",
                "severity", "visit_date", "predicted_risk",
            ]
            existing_cols = [c for c in display_cols if c in geo_df.columns]
            st.dataframe(
                geo_df[existing_cols],
                use_container_width=True,
                hide_index=True,
            )


# ═════════════════════════════════════════════════════════════
#  Trend Analysis Tab
# ═════════════════════════════════════════════════════════════

def _render_trend_analysis():
    """Show case trends over time with date slider and charts."""
    st.markdown("#### 📈 Consultation Trend Analysis")
    st.caption(
        "Track how consultation case counts and severity evolve over time. "
        "Use the date slider to zoom into a specific period."
    )

    results = st.session_state.get("hm_results")
    if not results or results.get("trend_df") is None or results["trend_df"].empty:
        st.info(
            "Generate a heatmap first on the **🗺️ Heatmap Dashboard** tab "
            "to populate trend data."
        )
        return

    trend_df: pd.DataFrame = results["trend_df"].copy()
    geo_df: pd.DataFrame = results.get("geo_df", pd.DataFrame())

    # ── Date range slider ────────────────────────────────────
    if len(trend_df) >= 2:
        all_dates = sorted(trend_df["date"].tolist())
        min_d, max_d = all_dates[0], all_dates[-1]
        selected = st.slider(
            "Date Range",
            min_value=min_d,
            max_value=max_d,
            value=(min_d, max_d),
            key="trend_slider",
        )
        trend_df = trend_df[
            (trend_df["date"] >= selected[0]) & (trend_df["date"] <= selected[1])
        ]

    if trend_df.empty:
        st.warning("No data in selected date range.")
        return

    # ── Summary metrics ──────────────────────────────────────
    with st.container(border=True):
        t1, t2, t3 = st.columns(3)
        t1.metric("Total Cases (period)", int(trend_df["cases"].sum()))
        t2.metric("Peak Day Cases", int(trend_df["cases"].max()))
        t3.metric("Avg Severity", f"{trend_df['avg_severity'].mean():.2f} / 3")

    # ── Daily case count chart ───────────────────────────────
    with st.container(border=True):
        st.markdown("##### Daily Consultation Cases")
        chart_data = trend_df.set_index("date")[["cases"]].rename(columns={"cases": "Cases"})
        st.bar_chart(chart_data)

    # ── Cumulative growth chart ──────────────────────────────
    with st.container(border=True):
        st.markdown("##### Cumulative Case Growth")
        cum_data = trend_df.set_index("date")[["cumulative_cases"]].rename(
            columns={"cumulative_cases": "Cumulative Cases"}
        )
        st.area_chart(cum_data)

    # ── Average severity over time ───────────────────────────
    with st.container(border=True):
        st.markdown("##### Average Severity Over Time")
        sev_data = trend_df.set_index("date")[["avg_severity"]].rename(
            columns={"avg_severity": "Avg Severity"}
        )
        st.line_chart(sev_data)

    # ── Diagnosis breakdown for selected period ──────────────
    if not geo_df.empty and "diagnosis" in geo_df.columns:
        with st.container(border=True):
            st.markdown("##### Top Diagnoses in Period")
            diag_counts = geo_df["diagnosis"].value_counts().head(10).reset_index()
            diag_counts.columns = ["Diagnosis", "Cases"]
            st.dataframe(diag_counts, use_container_width=True, hide_index=True)

