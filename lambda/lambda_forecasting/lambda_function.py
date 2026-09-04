"""
lambda_forecasting/lambda_function.py

AWS Lambda untuk Enrollment Forecasting.

Env vars (lihat .env.example):
  FORECASTING_MODEL_BUCKET, FORECASTING_MODEL_KEY,
  COURSE_EMBEDDINGS_TABLE, ENROLLMENT_HISTORY_TABLE, LEARNER_ACTIVITIES_TABLE

Request (POST /forecasts via API Gateway):
  { "course_id": "C0042", "days": 7 }

Response:
  { "course_id": "...", "forecast": [ {"date": "...", "predicted_enrollments": ...}, ... ] }
"""
import json
import logging
import os
import pickle
import re
import time
import uuid
from datetime import date, timedelta
from typing import Any, Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FORECASTING_MODEL_BUCKET = os.environ.get("FORECASTING_MODEL_BUCKET")
FORECASTING_MODEL_KEY = os.environ.get("FORECASTING_MODEL_KEY")
COURSE_EMBEDDINGS_TABLE = os.environ.get("COURSE_EMBEDDINGS_TABLE")
ENROLLMENT_HISTORY_TABLE = os.environ.get("ENROLLMENT_HISTORY_TABLE")
LEARNER_ACTIVITIES_TABLE = os.environ.get("LEARNER_ACTIVITIES_TABLE")

MAX_DAYS = 365
MIN_DAYS = 1

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

_model: Optional[Any] = None
_model_loaded_at: Optional[float] = None


def load_model() -> Any:
    """Download and unpickle the forecasting model from S3 (cached)."""
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


def validate_course_id(course_id: Any) -> str:
    """Validate the course_id format (e.g. C00001)."""
    course_id = str(course_id).strip()
    if not re.fullmatch(r"C\d{4,}", course_id):
        raise ValueError(f"Invalid course_id format: {course_id!r}")
    return course_id


def validate_days(days: Any) -> int:
    """Validate and clamp the forecast horizon (1-365 days)."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid days value: {days!r}") from None

    if days < MIN_DAYS or days > MAX_DAYS:
        raise ValueError(f"days must be between {MIN_DAYS} and {MAX_DAYS}")
    return days


def get_enrollment_history(course_id: str) -> Optional[dict]:
    """Query historical enrollment data from DynamoDB."""
    if not ENROLLMENT_HISTORY_TABLE:
        raise RuntimeError("ENROLLMENT_HISTORY_TABLE environment variable is required")

    table = dynamodb.Table(ENROLLMENT_HISTORY_TABLE)
    response = table.get_item(Key={"course_id": course_id})
    return response.get("Item")


def run_forecast(model: Any, history: Optional[dict], course_id: str, days: int) -> list[dict]:
    """Generate a daily enrollment forecast for the requested horizon."""
    base = _baseline_daily_enrollments(history)

    if model is not None and history and hasattr(model, "predict"):
        try:
            future = model.predict(days=days).tolist()
            return [{
                "date": (date.today() + timedelta(days=i)).isoformat(),
                "predicted_enrollments": round(max(0.0, float(v)), 2),
            } for i, v in enumerate(future)]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Model forecast failed (%s); falling back to baseline", exc
            )

    return [{
        "date": (date.today() + timedelta(days=i)).isoformat(),
        "predicted_enrollments": round(max(0.0, base * (1 + 0.02 * i)), 2),
    } for i in range(days)]


def _baseline_daily_enrollments(history: Optional[dict]) -> float:
    """Derive a naive baseline (avg daily enrollments) from history."""
    if not history:
        return 0.0
    total = _safe_float(history.get("total_enrollments", 0))
    days = _safe_float(history.get("history_days", 30))
    if days <= 0:
        return 0.0
    return total / days


def _safe_float(value: Any) -> float:
    """Convert a value to float, returning 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_ok_response(payload: dict, status: int = 200) -> dict:
    """Build a standard API Gateway HTTP response."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
        },
        "body": json.dumps(payload),
    }


def build_error_response(error: BaseException, status: int = 500) -> dict:
    """Build a standard API Gateway error response."""
    logger.error("Request failed: %s", error, exc_info=True)
    return build_ok_response(
        {"error": type(error).__name__, "message": str(error)}, status=status
    )


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point."""
    request_id = getattr(context, "aws_request_id", str(uuid.uuid4()))
    logger.info("Request %s received", request_id)

    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        course_id = validate_course_id(body.get("course_id"))
        days = validate_days(body.get("days", 7))

        model = load_model()
        history = get_enrollment_history(course_id)
        forecast = run_forecast(model, history, course_id, days)

        logger.info(
            "Request %s complete: course=%s days=%d forecast_len=%d",
            request_id, course_id, days, len(forecast),
        )
        return build_ok_response({
            "course_id": course_id,
            "forecast": forecast,
        })
    except (ValueError, json.JSONDecodeError) as exc:
        return build_error_response(exc, status=400)
    except Exception as exc:  # noqa: BLE001
        return build_error_response(exc)
