"""
lambda_recommendation/lambda_function.py

AWS Lambda untuk Risk Prediction (AgroSense). Folder ini adalah hasil migrasi
dari logika rekomendasi EduPintar -> risiko gagal panen.

Env vars (lihat .env.example):
  MODEL_BUCKET, MODEL_KEY, FARMS_TABLE, CROP_TABLE

Trigger: API Gateway (sinkron). Request:
  { "farm_id": "F00001", "crop_id": "C00001" }

Response:
  { "farm_id": "...", "crop_id": "...", "risk_percentage": 0.0-100.0 }

Tambahan:
  - Jika risk_percentage > 70, publish custom CloudWatch metric
    `HighRiskFarmCount` (namespace `AgroSense/Business`) via put_metric_data.
"""
import json
import logging
import os
import pickle
import re
import time
import uuid
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_BUCKET = os.environ.get("MODEL_BUCKET")
MODEL_KEY = os.environ.get("MODEL_KEY")
FARMS_TABLE = os.environ.get("FARMS_TABLE")
CROP_TABLE = os.environ.get("CROP_TABLE")

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
cloudwatch = boto3.client("cloudwatch")

HIGH_RISK_THRESHOLD = 70.0
NAMESPACE = "AgroSense/Business"
METRIC_NAME = "HighRiskFarmCount"

_model: Any | None = None
_model_loaded_at: float | None = None


def load_model() -> Any:
    """Download dan unpickle model dari S3 (cache di luar handler)."""
    global _model, _model_loaded_at

    if _model is not None and _model_loaded_at is not None:
        return _model

    if not MODEL_BUCKET or not MODEL_KEY:
        raise RuntimeError("MODEL_BUCKET and MODEL_KEY environment variables are required")

    logger.info("Loading model from s3://%s/%s", MODEL_BUCKET, MODEL_KEY)
    obj = s3.get_object(Bucket=MODEL_BUCKET, Key=MODEL_KEY)
    _model = pickle.loads(obj["Body"].read())
    _model_loaded_at = time.time()
    logger.info("Model loaded successfully")
    return _model


def get_farm_features(farm_id: str) -> dict | None:
    """Query fitur farm dari DynamoDB (FARMS_TABLE)."""
    if not FARMS_TABLE:
        raise RuntimeError("FARMS_TABLE environment variable is required")

    table = dynamodb.Table(FARMS_TABLE)
    response = table.get_item(Key={"farm_id": farm_id})
    return response.get("Item")


def get_crop_features(crop_id: str) -> dict | None:
    """Query fitur crop dari DynamoDB (CROP_TABLE)."""
    if not CROP_TABLE:
        raise RuntimeError("CROP_TABLE environment variable is required")

    table = dynamodb.Table(CROP_TABLE)
    response = table.get_item(Key={"crop_id": crop_id})
    return response.get("Item")


def validate_farm_id(farm_id: Any) -> str:
    """Validasi format farm_id (mis. F00001)."""
    farm_id = str(farm_id).strip()
    if not re.fullmatch(r"F\d{4,}", farm_id):
        raise ValueError(f"Invalid farm_id format: {farm_id!r}")
    return farm_id


def validate_crop_id(crop_id: Any) -> str:
    """Validasi format crop_id (mis. C00001)."""
    crop_id = str(crop_id).strip()
    if not re.fullmatch(r"C\d{4,}", crop_id):
        raise ValueError(f"Invalid crop_id format: {crop_id!r}")
    return crop_id


def build_response(payload: dict, status: int = 200) -> dict:
    """Buat response standar API Gateway."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
        },
        "body": json.dumps(payload),
    }


def emit_high_risk_metric(count: int = 1) -> None:
    """Publish custom CloudWatch metric HighRiskFarmCount."""
    cloudwatch.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{
            "MetricName": METRIC_NAME,
            "Value": float(count),
            "Unit": "Count",
        }],
    )
    logger.info("Published %s=%s to %s", METRIC_NAME, count, NAMESPACE)


def compute_risk_percentage(model: Any, farm_features: dict, crop_features: dict) -> float:
    """Jalankan model dan Kembalikan risk_percentage (0-100)."""
    if model is None:
        return 0.0

    try:
        features = _flatten_features(farm_features, crop_features)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba([features])[0]
            # proba[1] = probabilitas kelas positif (gagal panen)
            if len(proba) >= 2:
                score = float(proba[1]) * 100.0
            else:
                score = float(proba[0]) * 100.0
        elif hasattr(model, "predict"):
            score = float(model.predict([features])[0])
        else:
            logger.warning("Model has no predict/predict_proba; returning 0")
            return 0.0
        return max(0.0, min(100.0, score))
    except Exception:  # noqa: BLE001
        logger.exception("Model inference failed")
        return 0.0


def _flatten_features(farm_features: dict, crop_features: dict) -> list[float]:
    """Flatten fitur farm + crop menjadi vektor numerik sesuai RISK_FEATURES."""
    vector: list[float] = []
    for key in [
        "farm_size_hectare",
        "total_activities",
        "total_activity_volume",
        "avg_activity_volume",
        "crop_diversity",
        "region_avg_quantity",
        # Transitif crop
        "avg_yield_ton_per_ha",
    ]:
        if key in farm_features:
            vector.append(_safe_float(farm_features.get(key)))
        else:
            vector.append(_safe_float(crop_features.get(key)))
    return vector


def _safe_float(value: Any) -> float:
    """Konversi ke float, 0.0 bila gagal."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def lambda_handler(event: dict, context: Any) -> dict:
    """Entry point utama Lambda."""
    request_id = getattr(context, "aws_request_id", str(uuid.uuid4()))
    logger.info("Request %s received", request_id)

    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        farm_id = validate_farm_id(body.get("farm_id"))
        crop_id = validate_crop_id(body.get("crop_id"))

        farm_features = get_farm_features(farm_id)
        crop_features = get_crop_features(crop_id)
        if farm_features is None:
            return build_response(
                {"error": "FarmNotFound", "message": f"Farm {farm_id} tidak ditemukan"},
                status=404,
            )
        if crop_features is None:
            return build_response(
                {"error": "CropNotFound", "message": f"Crop {crop_id} tidak ditemukan"},
                status=404,
            )

        model = load_model()
        risk = compute_risk_percentage(model, farm_features, crop_features)

        if risk > HIGH_RISK_THRESHOLD:
            emit_high_risk_metric()

        logger.info("Request %s complete: risk=%.2f", request_id, risk)
        return build_response({
            "farm_id": farm_id,
            "crop_id": crop_id,
            "risk_percentage": round(risk, 2),
        })
    except (ValueError, json.JSONDecodeError) as exc:
        return build_response(
            {"error": type(exc).__name__, "message": str(exc)}, status=400
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Request failed: %s", exc)
        return build_response(
            {"error": type(exc).__name__, "message": str(exc)}, status=500
        )