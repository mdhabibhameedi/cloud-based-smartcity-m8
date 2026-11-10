import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data/raw/traffic_synthetic.csv"
MODELS = BASE / "models"
RESULTS = BASE / "results"

MODELS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

# Load and sort historical observations.
df = pd.read_csv(DATA)
df["timestamp_utc"] = pd.to_datetime(
    df["timestamp_utc"], utc=True
)
df = df.sort_values(
    ["zone_id", "timestamp_utc"]
).reset_index(drop=True)

# Validate the input.
assert not df["vehicle_count"].isna().any()
assert not df.duplicated(
    ["zone_id", "timestamp_utc"]
).any()
assert (df["vehicle_count"] >= 0).all()

# Build forecasting features from past observations.
group = df.groupby("zone_id")["vehicle_count"]

df["lag_1"] = group.shift(1)
df["lag_24"] = group.shift(24)
df["hour"] = df["timestamp_utc"].dt.hour
df["day_of_week"] = df["timestamp_utc"].dt.dayofweek

df = df.dropna(
    subset=["lag_1", "lag_24"]
).copy()

features = pd.get_dummies(
    df[["zone_id", "hour", "day_of_week",
        "lag_1", "lag_24"]],
    columns=["zone_id"],
    dtype=int,
)

target = df["vehicle_count"]

# Split by time, not by randomly shuffled rows.
timestamps = sorted(df["timestamp_utc"].unique())
cutoff = timestamps[int(len(timestamps) * 0.8)]

train_mask = df["timestamp_utc"] < cutoff
test_mask = ~train_mask

X_train = features.loc[train_mask]
X_test = features.loc[test_mask]

y_train = target.loc[train_mask]
y_test = target.loc[test_mask]

model = RandomForestRegressor(
    n_estimators=150,
    max_depth=12,
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1,
)

model.fit(X_train, y_train)

predictions = np.maximum(
    model.predict(X_test), 0
)

# Seasonal naive baseline: same hour yesterday.
baseline = df.loc[test_mask, "lag_24"].to_numpy()


def evaluate(actual, predicted):
    return {
        "MAE": round(
            float(mean_absolute_error(actual, predicted)), 4
        ),
        "RMSE": round(
            float(np.sqrt(
                mean_squared_error(actual, predicted)
            )), 4
        ),
        "R2": round(
            float(r2_score(actual, predicted)), 4
        ),
    }


metrics = {
    "dataset": "Synthetic Newvale traffic data",
    "train_records": int(train_mask.sum()),
    "test_records": int(test_mask.sum()),
    "split_timestamp": str(cutoff),
    "baseline": evaluate(y_test, baseline),
    "random_forest": evaluate(y_test, predictions),
}

# Save model and evaluation results.
joblib.dump(
    {"model": model, "features": list(features.columns)},
    MODELS / "traffic_model.joblib",
)

with open(
    RESULTS / "traffic_metrics.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(metrics, f, indent=2)

output = df.loc[
    test_mask,
    ["timestamp_utc", "zone_id", "vehicle_count"]
].copy()

output["baseline_prediction"] = baseline
output["model_prediction"] = predictions

output.to_csv(
    RESULTS / "traffic_predictions.csv",
    index=False,
)

# Interactive comparison for one representative zone.
chart_data = output[
    output["zone_id"] == "Z01"
].sort_values("timestamp_utc").tail(72)

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=chart_data["timestamp_utc"],
    y=chart_data["vehicle_count"],
    name="Actual",
    mode="lines",
))

fig.add_trace(go.Scatter(
    x=chart_data["timestamp_utc"],
    y=chart_data["model_prediction"],
    name="Predicted",
    mode="lines",
))

fig.update_layout(
    title="Newvale Traffic: Actual vs Predicted",
    xaxis_title="Timestamp (UTC)",
    yaxis_title="Vehicle Count per Hour",
    template="plotly_white",
)

fig.write_html(
    str(RESULTS / "traffic_prediction_chart.html")
)

print("\nTRAFFIC MODEL TRAINING COMPLETED")
print(json.dumps(metrics, indent=2))
print("\nModel, predictions, metrics and chart saved.")