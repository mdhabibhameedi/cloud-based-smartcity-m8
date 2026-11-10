import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)

# Stage 7 predictions and Stage 4 energy dataset.
traffic = pd.read_csv(
    RESULTS / "traffic_predictions.csv"
)
energy = pd.read_csv(
    BASE / "data/raw/energy_synthetic.csv"
)

# Standardise timestamps for reliable matching.
for df in (traffic, energy):
    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"], utc=True
    )

keys = ["timestamp_utc", "zone_id"]

if traffic.duplicated(keys).any():
    raise ValueError("Duplicate traffic prediction keys")

if energy.duplicated(keys).any():
    raise ValueError("Duplicate energy observation keys")

# Integrate traffic predictions with street-lighting records.
df = traffic.merge(
    energy,
    on=keys,
    how="left",
    validate="one_to_one",
    indicator=True
)

if not (df["_merge"] == "both").all():
    raise ValueError("Missing matching energy records")

df = df.drop(columns="_merge")

required = [
    "model_prediction", "energy_kwh", "lamp_count",
    "rated_power_w", "interval_minutes", "lighting_on"
]

if df[required].isna().any().any():
    raise ValueError("Missing values in simulation inputs")

if (
    (df["model_prediction"] < 0).any()
    or (df["energy_kwh"] < 0).any()
    or (~df["lighting_on"].isin([0, 1])).any()
    or (df["lamp_count"] <= 0).any()
    or (df["rated_power_w"] <= 0).any()
    or (df["interval_minutes"] <= 0).any()
):
    raise ValueError("Invalid simulation input values")

# Brightness control: hypothetical traffic-based strategy.
# These are modelling assumptions, not deployed lighting rules.
df["brightness_factor"] = np.select(
    [
        df["model_prediction"] < 20,
        df["model_prediction"] < 60
    ],
    [0.40, 0.70],
    default=1.00
)

# Respect the lighting schedule: do not activate off lights.
df.loc[
    df["lighting_on"] == 0, "brightness_factor"
] = 0.0

# Use the energy dataset as the fixed-lighting reference.
df["fixed_kwh"] = df["energy_kwh"]

# Estimated adaptive energy under a linear dimming assumption.
df["adaptive_kwh"] = (
    df["fixed_kwh"] * df["brightness_factor"]
)

df["estimated_savings_kwh"] = (
    df["fixed_kwh"] - df["adaptive_kwh"]
)

# Independent theoretical baseline sanity check.
df["theoretical_fixed_kwh"] = (
    df["lamp_count"]
    * df["rated_power_w"]
    / 1000
    * df["interval_minutes"]
    / 60
    * df["lighting_on"]
)

fixed = float(df["fixed_kwh"].sum())
adaptive = float(df["adaptive_kwh"].sum())
savings = fixed - adaptive

if fixed <= 0:
    raise ValueError("Fixed lighting energy must be positive")

summary = {
    "project": "Newvale Smart City",
    "stage": "Cross-Service Innovation",
    "method": "Predicted traffic-based adaptive lighting",
    "data_type": "Synthetic",
    "matched_records": int(len(df)),
    "test_period_start": str(df["timestamp_utc"].min()),
    "test_period_end": str(df["timestamp_utc"].max()),
    "fixed_lighting_kwh": round(fixed, 3),
    "adaptive_lighting_kwh": round(adaptive, 3),
    "estimated_savings_kwh": round(savings, 3),
    "estimated_savings_percent": round(
        100 * savings / fixed, 2
    ),
    "theoretical_fixed_lighting_kwh": round(
        float(df["theoretical_fixed_kwh"].sum()), 3
    ),
    "assumptions": {
        "traffic_below_20": "40% brightness",
        "traffic_20_to_59": "70% brightness",
        "traffic_60_and_above": "100% brightness",
        "lights_off": "0% brightness",
        "dimming_energy_model": "Linear approximation",
        "fixed_baseline": "Synthetic energy_kwh observations",
        "real_world_savings": "Not measured",
        "safety_validation": "Not performed"
    }
}

# Save reproducible results.
df.to_csv(
    RESULTS / "adaptive_lighting_results.csv",
    index=False
)

with open(
    RESULTS / "adaptive_lighting_summary.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(summary, f, indent=2)

# Visual comparison.
fig = go.Figure()

fig.add_bar(
    x=["Fixed Lighting", "Adaptive Lighting"],
    y=[fixed, adaptive],
    text=[round(fixed, 2), round(adaptive, 2)],
    textposition="auto"
)

fig.update_layout(
    title="Newvale Smart City - Simulated Lighting Energy",
    xaxis_title="Lighting Strategy",
    yaxis_title="Estimated Energy Consumption (kWh)",
    template="plotly_white",
    annotations=[dict(
        text=(
            f"Estimated savings: "
            f"{summary['estimated_savings_percent']}%"
        ),
        x=0.5, y=1.12,
        xref="paper", yref="paper",
        showarrow=False
    )],
    margin=dict(t=110)
)

fig.write_html(
    str(RESULTS / "adaptive_lighting_chart.html")
)

print("\nSTAGE 8 - CROSS-SERVICE INNOVATION")
print("SIMULATION COMPLETED")
print(json.dumps(summary, indent=2))