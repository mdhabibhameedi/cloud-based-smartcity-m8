import json
import boto3
import hashlib
import logging
import math
from datetime import datetime, timezone
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

BUCKET = "newvale-smartcity-m8"


def save_if_new(key, data):
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(data),
            ContentType="application/json",
            IfNoneMatch="*"
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] in (
            "PreconditionFailed", "412"
        ):
            return False
        raise


def lambda_handler(event, context):
    try:
        if not isinstance(event, dict):
            raise ValueError("Event must be a JSON object")

        sensor_type = event.get("sensor_type")
        timestamp = event.get("timestamp")

        if sensor_type not in ("traffic", "energy"):
            raise ValueError("Invalid sensor_type")

        if not isinstance(timestamp, str):
            raise ValueError("Missing or invalid timestamp")

        datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )

        if sensor_type == "traffic":
            value = event.get("vehicle_count")
            if type(value) is not int or value < 0:
                raise ValueError("Invalid vehicle_count")
        else:
            value = event.get("consumption_kwh")
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value < 1000000
            ):
                raise ValueError("Invalid consumption_kwh")

        canonical = json.dumps(
            event, sort_keys=True, separators=(",", ":")
        )

        record_id = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

        raw_key = (
            f"raw-sensor-data/{sensor_type}/{record_id}.json"
        )
        processed_key = (
            f"processed-data/{sensor_type}/{record_id}.json"
        )

        raw_created = save_if_new(raw_key, event)

        processed = {
            "record_id": record_id,
            "sensor_type": sensor_type,
            "timestamp": timestamp,
            "received_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "validated",
            "data": event
        }

        processed_created = save_if_new(
            processed_key, processed
        )

        duplicate = not raw_created and not processed_created

        if duplicate:
            logger.info("Duplicate sensor record: %s", record_id)
        else:
            logger.info("Sensor record stored: %s", record_id)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": (
                    "Duplicate ignored"
                    if duplicate
                    else "Sensor data stored successfully"
                ),
                "record_id": record_id,
                "duplicate": duplicate
            })
        }

    except Exception as error:
        logger.error("Sensor processing failed: %s", str(error))
        raise
