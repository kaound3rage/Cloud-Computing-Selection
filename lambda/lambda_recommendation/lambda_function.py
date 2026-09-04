"""
lambda_recommendation/lambda_function.py

AWS Lambda untuk Intelligent Course Recommendation.

Env vars (lihat .env.example):
  MODEL_BUCKET, MODEL_KEY, LEARNERS_TABLE, COURSE_TABLE

Request (POST /predict via API Gateway):
  { "learner_id": "L0001", "course_id": "C0042" }

Response:
  { "learner_id": "...", "course_id": "...", "recommendation_percentage": 0.0-100.0 }
"""
import json
import logging
import os
import pickle
import re
import time
import uuid
from typing import Any, Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_BUCKET = os.environ.get("MODEL_BUCKET")
MODEL_KEY = os.environ.get("MODEL_KEY")
LEARNERS_TABLE = os.environ.get("LEARNERS_TABLE")
COURSE_TABLE = os.environ.get("COURSE_TABLE")

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

_model: Optional[Any] = None
_model_loaded_at: Optional[float] = None


def load_model() -> Any:
    """Download and unpickle the model from S3 (cached across invocations)."""
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


def get_learner_features(learner_id: str) -> Optional[dict]:
    """Query learner features from DynamoDB."""
    if not LEARNERS_TABLE:
        raise RuntimeError("LEARNERS_TABLE environment variable is required")

    table = dynamodb.Table(LEARNERS_TABLE)
    response = table.get_item(Key={"learner_id": learner_id})
    return response.get("Item")


def get_course_features(course_id: str) -> Optional[dict]:
    """Query course features from DynamoDB."""
    if not COURSE_TABLE:
        raise RuntimeError("COURSE_TABLE environment variable is required")

    table = dynamodb.Table(COURSE_TABLE)
    response = table.get_item(Key={"course_id": course_id})
    return response.get("Item")


def validate_learner_id(learner_id: Any) -> str:
    """Validate the learner_id format (e.g. L00001)."""
    learner_id = str(learner_id).strip()
    if not re.fullmatch(r"L\d{4,}", learner_id):
        raise ValueError(f"Invalid learner_id format: {learner_id!r}")
    return learner_id


def validate_course_id(course_id: Any) -> str:
    """Validate the course_id format (e.g. C00001)."""
    course_id = str(course_id).strip()
    if not re.fullmatch(r"C\d{4,}", course_id):
        raise ValueError(f"Invalid course_id format: {course_id!r}")
    return course_id


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


def build_error_response(error: BaseException) -> dict:
    """Build a standard API Gateway error response."""
    logger.error("Request failed: %s", error, exc_info=True)
    return build_ok_response(
        {"error": type(error).__name__, "message": str(error)}, status=500
    )


def compute_recommendation(model: Any, learner_features: dict, course_features: dict) -> float:
    """Run the model and return a recommendation percentage."""
    if model is None:
        return 0.0

    try:
        if hasattr(model, "predict_proba"):
            features = _flatten_features(learner_features, course_features)
            proba = model.predict_proba([features])[0]
            score = float(max(proba)) * 100.0
        elif hasattr(model, "predict"):
            features = _flatten_features(learner_features, course_features)
            score = float(model.predict([features])[0])
        else:
            logger.warning("Model has no predict/predict_proba; returning 0")
            return 0.0
        return max(0.0, min(100.0, score))
    except Exception as exc:  # noqa: BLE001
        logger.error("Model inference failed: %s", exc, exc_info=True)
        return 0.0


def _flatten_features(learner_features: dict, course_features: dict) -> list[float]:
    """Flatten learner + course features into a numeric vector."""
    vector: list[float] = []

    for key in ["total_courses_completed", "total_activities", "total_study_minutes"]:
        vector.append(_safe_float(learner_features.get(key)))

    for key in ["avg_rating", "duration_hours"]:
        vector.append(_safe_float(course_features.get(key)))

    is_premium = 1.0 if course_features.get("is_premium") else 0.0
    vector.append(is_premium)

    return vector


def _safe_float(value: Any) -> float:
    """Convert a value to float, returning 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point."""
    request_id = getattr(context, "aws_request_id", str(uuid.uuid4()))
    logger.info("Request %s received", request_id)

    try:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)

        learner_id = validate_learner_id(body.get("learner_id"))
        course_id = validate_course_id(body.get("course_id"))

        learner_features = get_learner_features(learner_id) or {}
        course_features = get_course_features(course_id) or {}

        model = load_model()
        score = compute_recommendation(model, learner_features, course_features)

        logger.info("Request %s complete: score=%.2f", request_id, score)
        return build_ok_response({
            "learner_id": learner_id,
            "course_id": course_id,
            "recommendation_percentage": round(score, 2),
        })
    except (ValueError, json.JSONDecodeError) as exc:
        return build_ok_response(
            {"error": type(exc).__name__, "message": str(exc)}, status=400
        )
    except Exception as exc:  # noqa: BLE001
        return build_error_response(exc)
