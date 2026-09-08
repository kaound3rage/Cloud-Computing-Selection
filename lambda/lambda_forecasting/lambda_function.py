"""
lambda_forecasting/lambda_function.py

AWS Lambda untuk Yield Forecasting (AgroSense). Folder ini adalah hasil migrasi
dari logika forecasting enrollment EduPintar -> forecast hasil panen.

Env vars (lihat .env.example):
  FORECASTING_MODEL_BUCKET, FORECASTING_MODEL_KEY,
  CROP_FEATURES_TABLE, YIELD_HISTORY_TABLE, FARM_ACTIVITIES_TABLE

Trigger: EventBridge Schedule (bukan API Gateway). Bisa juga dipicu manual
(invoke langsung) untuk testing.

Perilaku:
  - Untuk setiap crop, hitung forecast volume panen beberapa periode ke depan.
  - Tulis hasil sebagai ITEM BARU ke DynamoDB `YIELD_HISTORY_TABLE` dengan:
      crop_id, forecast_period, forecast_quantity_ton, generated_at (timestamp).
  - Return function berupa summary singkat (untuk log CloudWatch), bukan
    dikonsumi caller.
"""
import json
import logging
import math
import os
import pickle
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FORECASTING_MODEL_BUCKET = os.environ.get("FORECASTING_MODEL_BUCKET")
FORECASTING_MODEL_KEY = os.environ.get("FORECASTING_MODEL_KEY")
CROP_FEATURES_TABLE = os.environ.get("CROP_FEATURES_TABLE")
YIELD_HISTORY_TABLE = os.environ.get("YIELD_HISTORY_TABLE")
FARM_ACTIVITIES_TABLE = os.environ.get("FARM_ACTIVITIES_TABLE")

FORECAST_PERIODS = int(os.environ.get("FORECAST_PERIODS", "8"))

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

_model: Any | None = None
_model_loaded_at: float | None = None


def load_model() -> Any:
    """Download dan unpickle yield model dari S3 (cached)."""
    global _model, _model_loaded_at

    if _model is not None and _model_loaded_at is not None:
        return _model

    if not FORECASTING_MODEL_BUCKET or not FORECASTING_MODEL_KEY:
        raise RuntimeError(
            "FORECASTING_MODEL_BUCKET and FORECASTING_MODEL_KEY are required"
        )

    logger.info(
        "Loading forecasting model from s3://%s/%s",
        FORECASTING_MODEL_BUCKET,
        FORECASTING_MODEL_KEY,
    )
    obj = s3.get_object(Bucket=FORECASTING_MODEL_BUCKET, Key=FORECASTING_MODEL_KEY)
    _model = pickle.loads(obj["Body"].read())
    _model_loaded_at = time.time()
    logger.info("Forecasting model loaded successfully")
    return _model


def list_crop_ids() -> list[str]:
    """Ambil daftar crop dari CROP_FEATURES_TABLE (scan, batasi konsumsi)."""
    if not CROP_FEATURES_TABLE:
        raise RuntimeError("CROP_FEATURES_TABLE environment variable is required")
    table = dynamodb.Table(CROP_FEATURES_TABLE)
    seen: set[str] = set()
    scan_kwargs: dict[str, Any] = {"ProjectionExpression": "crop_id"}
    while True:
        response = table.scan(**scan_kwargs)
        for item in response.get("Items", []):
            cid = item.get("crop_id")
            if cid:
                seen.add(cid)
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    logger.info("Found %d crops in %s", len(seen), CROP_FEATURES_TABLE)
    return sorted(seen)


def get_crop_baseline(crop_id: str) -> float:
    """Ambil baseline yield per crop (fallback untuk forecast tanpa model)."""
    if not CROP_FEATURES_TABLE:
        return 1.0
    table = dynamodb.Table(CROP_FEATURES_TABLE)
    response = table.get_item(Key={"crop_id": crop_id})
    item = response.get("Item") or {}
    val = item.get("avg_yield_ton_per_ha") or item.get("avg_quantity_ton") or 1.0
    return _safe_float(val, 1.0)


def run_forecast(model: Any, crop_id: str) -> list[dict]:
    """Hitung forecast N periode untuk sebuah crop.

    Jika model punya predict, gunakan fitur period_offset + musiman (sin/cos).
    Fallback: baseline + tren kecil per periode.
    """
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for period in range(1, FORECAST_PERIODS + 1):
        qty = _forecast_for_period(model, crop_id, period)
        rows.append({
            "crop_id": crop_id,
            "forecast_period": f"period_{period}",
            "forecast_quantity_ton": round(qty, 2),
            "generated_at": now.isoformat(timespec="seconds"),
        })
    return rows


def _forecast_for_period(model: Any, crop_id: str, period: int) -> float:
    """Prediksi qty untuk 1 periode; default -10% jika inference gagal."""
    try:
        if model is not None and hasattr(model, "predict"):
            off = float(period - 1)
            features = [off, float(math.sin(2 * math.pi * off / 12)),
                        float(math.cos(2 * math.pi * off / 12))]
            value = model.predict([features])[0]
            return max(0.0, float(value))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Forecast inference failed crop=%s: %s", crop_id, exc)
    return max(0.0, get_crop_baseline(crop_id) * 0.9)


def write_yield_history(items: list[dict]) -> None:
    """Tulis item forecast sebagai item baru ke YIELD_HISTORY_TABLE."""
    if not YIELD_HISTORY_TABLE:
        raise RuntimeError("YIELD_HISTORY_TABLE environment variable is required")
    table = dynamodb.Table(YIELD_HISTORY_TABLE)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    logger.info("Wrote %d items to %s", len(items), YIELD_HISTORY_TABLE)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Konversi ke float dengan default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def lambda_handler(event: dict, context: Any) -> dict:
    """Entry point utama Lambda (EventBridge Schedule / manual invoke)."""
    run_id = getattr(context, "aws_request_id", str(uuid.uuid4()))
    logger.info("Run %s received (event keys: %s)", run_id, list((event or {}).keys()))

    model = load_model()
    crop_ids = list_crop_ids()
    if not crop_ids:
        logger.warning("No crops found; nothing to forecast")
        return {"run_id": run_id, "crops_processed": 0, "status": "no_crops"}

    total_items = 0
    for crop_id in crop_ids:
        forecast = run_forecast(model, crop_id)
        write_yield_history(forecast)
        total_items += len(forecast)

    summary = {
        "run_id": run_id,
        "crops_processed": len(crop_ids),
        "forecast_items_written": total_items,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    logger.info("Yield forecasting complete: %s", json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    print(json.dumps(lambda_handler({"source": "manual-test"}, None), ensure_ascii=False))