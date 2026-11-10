import csv
import json
import os
import ssl
import time
from pathlib import Path
from datetime import datetime, timezone
from tkinter import Tk, filedialog

import certifi
import paho.mqtt.client as mqtt


BASE = Path(__file__).resolve().parents[1]

SENSORS = [
    {
        "name": "Newvale-Traffic-Sensor-01",
        "topic": "newvale/traffic/telemetry",
        "file": BASE / "data/raw/traffic_synthetic.csv",
        "type": "traffic",
    },
    {
        "name": "Newvale-Energy-Sensor-01",
        "topic": "newvale/energy/telemetry",
        "file": BASE / "data/raw/energy_synthetic.csv",
        "type": "energy",
    },
]


def choose_file(title):
    path = filedialog.askopenfilename(title=title)
    if not path:
        raise RuntimeError("Certificate selection cancelled")
    return path


def prepare_message(row, sensor_type):
    message = {
        "sensor_type": sensor_type,
        "record_id": row["record_id"],
        "timestamp": row["timestamp_utc"],
        "zone_id": row["zone_id"],
        "is_synthetic": True,
        "sent_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if sensor_type == "traffic":
        message["vehicle_count"] = int(row["vehicle_count"])
    else:
        message["consumption_kwh"] = float(row["energy_kwh"])

    return message


def publish_sensor(sensor, endpoint):
    print(f"\nConnecting: {sensor['name']}")

    cert = choose_file(
        f"Select certificate for {sensor['name']}"
    )
    key = choose_file(
        f"Select PRIVATE KEY for {sensor['name']}"
    )

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=sensor["name"],
        protocol=mqtt.MQTTv311,
    )

    tls_context = ssl.create_default_context(
        cafile=certifi.where()
    )
    tls_context.load_cert_chain(
        certfile=cert,
        keyfile=key,
    )
    client.tls_set_context(tls_context)

    state = {"connected": False, "error": None}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            state["connected"] = True
            print("MQTT connection successful")
        else:
            state["error"] = str(reason_code)

    client.on_connect = on_connect

    try:
        client.connect(endpoint, 8883, keepalive=60)
        client.loop_start()

        deadline = time.monotonic() + 15

        while not state["connected"]:
            if state["error"]:
                raise RuntimeError(state["error"])
            if time.monotonic() >= deadline:
                raise TimeoutError("MQTT connection timed out")
            time.sleep(0.1)

        with open(sensor["file"], newline="", encoding="utf-8-sig") as f:
            rows = []
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
                if len(rows) == 2:
                    break

        for row in rows:
            message = prepare_message(row, sensor["type"])

            result = client.publish(
                sensor["topic"],
                json.dumps(message),
                qos=1,
            )
            result.wait_for_publish(timeout=15)

            if not result.is_published():
                raise RuntimeError("MQTT publish not confirmed")

            print(f"Published: {message['record_id']}")

        return len(rows)

    finally:
        client.disconnect()
        client.loop_stop()


def main():
    endpoint = os.environ.get("NEWVALE_IOT_ENDPOINT")
    if not endpoint:
        raise SystemExit("Set NEWVALE_IOT_ENDPOINT to your IoT data endpoint hostname.")

    root = Tk()
    root.withdraw()

    total = 0

    try:
        for sensor in SENSORS:
            total += publish_sensor(sensor, endpoint)

        print("\nSIMULATOR COMPLETED")
        print(f"MQTT messages published: {total}")

    finally:
        root.destroy()


if __name__ == "__main__":
    main()