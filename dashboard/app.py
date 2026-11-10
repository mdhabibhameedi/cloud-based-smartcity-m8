from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results"
DATA = BASE / "data" / "raw"

st.set_page_config(
    page_title="Newvale Smart City",
    page_icon="🏙️",
    layout="wide"
)

st.title("🏙️ Newvale Smart City")
st.caption(
    "Cloud Infrastructure Monitoring | "
    "Historical Synthetic Data Demonstration"
)

@st.cache_data
def load_data():
    traffic = pd.read_csv(
        DATA / "traffic_synthetic.csv"
    )
    energy = pd.read_csv(
        DATA / "energy_synthetic.csv"
    )
    predictions = pd.read_csv(
        RESULTS / "traffic_predictions.csv"
    )
    lighting = pd.read_csv(
        RESULTS / "adaptive_lighting_results.csv"
    )
    return traffic, energy, predictions, lighting


try:
    traffic, energy, predictions, lighting = load_data()
except (FileNotFoundError, pd.errors.ParserError) as error:
    st.error(f"Unable to load project data: {error}")
    st.stop()

for frame in (traffic, energy, predictions, lighting):
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"], utc=True
    )

zones = sorted(traffic["zone_id"].unique())
selected_zone = st.sidebar.selectbox(
    "Select City Zone", ["All Zones"] + zones
)

threshold = st.sidebar.slider(
    "Traffic Alert Threshold",
    min_value=20,
    max_value=200,
    value=80,
    step=10
)

def filter_zone(frame):
    if selected_zone == "All Zones":
        return frame.copy()
    return frame[
        frame["zone_id"] == selected_zone
    ].copy()


t = filter_zone(traffic)
e = filter_zone(energy)
p = filter_zone(predictions)
l = filter_zone(lighting)

tabs = st.tabs([
    "Overview",
    "Traffic & Predictions",
    "Energy & Innovation",
    "Alerts",
    "Architecture"
])

with tabs[0]:
    st.subheader("City Infrastructure Overview")

    a, b, c, d = st.columns(4)

    a.metric("Traffic Readings", f"{len(t):,}")
    b.metric("Energy Readings", f"{len(e):,}")
    c.metric(
        "Average Traffic",
        f"{t['vehicle_count'].mean():.1f}"
    )
    d.metric(
        "Energy Consumption",
        f"{e['energy_kwh'].sum():,.1f} kWh"
    )

    st.info(
        "Data source: synthetic historical datasets. "
        "This dashboard does not claim live sensor monitoring."
    )

    st.write(
        "Latest traffic observation:",
        t["timestamp_utc"].max()
    )
    st.write(
        "Latest energy observation:",
        e["timestamp_utc"].max()
    )

    st.caption(
        "Data freshness is reported as the latest observation "
        "timestamp, not the time of the last cloud ingestion."
    )

with tabs[1]:
    st.subheader("Traffic Conditions")

    daily = (
        t.assign(
            date=t["timestamp_utc"].dt.date
        )
        .groupby("date", as_index=False)["vehicle_count"]
        .mean()
    )

    st.plotly_chart(
        px.line(
            daily,
            x="date",
            y="vehicle_count",
            title="Average Traffic by Day"
        ),
        use_container_width=True
    )

    st.subheader("AI Traffic Predictions")

    chart = p.sort_values("timestamp_utc")

    if selected_zone == "All Zones":
        chart = (
            chart.groupby(
                "timestamp_utc", as_index=False
            )[["vehicle_count", "model_prediction"]]
            .sum()
        )

    chart = chart.tail(72)

    st.plotly_chart(
        px.line(
            chart,
            x="timestamp_utc",
            y=["vehicle_count", "model_prediction"],
            labels={
                "value": "Vehicles per Hour",
                "variable": "Series"
            },
            title="Actual vs Predicted Traffic"
        ),
        use_container_width=True
    )

    st.caption(
        "Random Forest predictions evaluated against "
        "historical synthetic observations."
    )

with tabs[2]:
    st.subheader("Energy Consumption Trends")

    energy_daily = (
        e.assign(
            date=e["timestamp_utc"].dt.date
        )
        .groupby("date", as_index=False)["energy_kwh"]
        .sum()
    )

    st.plotly_chart(
        px.line(
            energy_daily,
            x="date",
            y="energy_kwh",
            title="Daily Energy Consumption (kWh)"
        ),
        use_container_width=True
    )

    st.subheader("Cross-Service Innovation")

    fixed = l["fixed_kwh"].sum()
    adaptive = l["adaptive_kwh"].sum()
    savings = fixed - adaptive
    percent = 100 * savings / fixed if fixed else 0

    a, b, c = st.columns(3)

    a.metric("Fixed Lighting", f"{fixed:,.2f} kWh")
    b.metric("Adaptive Lighting", f"{adaptive:,.2f} kWh")
    c.metric("Estimated Savings", f"{percent:.2f}%")

    comparison = pd.DataFrame({
        "Strategy": ["Fixed", "Adaptive"],
        "Energy (kWh)": [fixed, adaptive]
    })

    st.plotly_chart(
        px.bar(
            comparison,
            x="Strategy",
            y="Energy (kWh)",
            title="Simulated Street-Lighting Comparison"
        ),
        use_container_width=True
    )

    st.caption(
        "Results are simulated using synthetic data "
        "and assumed linear dimming. Savings are not "
        "real-world measurements."
    )

with tabs[3]:
    st.subheader("Traffic Congestion Alerts")

    latest_time = p["timestamp_utc"].max()
    latest = p[
        p["timestamp_utc"] == latest_time
    ]

    alerts = latest[
        latest["model_prediction"] >= threshold
    ]

    if alerts.empty:
        st.success(
            "No predicted congestion alerts at "
            "the selected historical observation."
        )
    else:
        st.warning(
            f"{len(alerts)} congestion alert(s) triggered."
        )
        st.dataframe(
            alerts[
                ["zone_id", "timestamp_utc",
                 "model_prediction"]
            ],
            hide_index=True
        )

    st.caption(
        "These are demonstration alerts evaluated against "
        "historical model predictions, not live notifications."
    )

with tabs[4]:
    st.subheader("Newvale Smart City Architecture")

    diagrams = list(
        (BASE / "docs").rglob("*architecture*.png")
    )

    if not diagrams:
        diagrams = list(
            (BASE / "docs").rglob("*.png")
        )

    if diagrams:
        st.image(
            str(diagrams[0]),
            caption="Newvale Smart City Architecture",
            use_container_width=True
        )
    else:
        st.info(
            "Architecture diagram is available "
            "in the project's documentation folder."
        )

st.divider()
st.caption(
    "Newvale Smart City | Cloud Computing "
    "Modular Assignment 8"
)