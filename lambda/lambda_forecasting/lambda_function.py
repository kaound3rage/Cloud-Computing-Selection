"""
lambda_forecasting/lambda_function.py

Env vars (lihat .env.example):
  FORECASTING_MODEL_BUCKET, FORECASTING_MODEL_KEY,
  COURSE_EMBEDDINGS_TABLE, ENROLLMENT_HISTORY_TABLE, LEARNER_ACTIVITIES_TABLE

Request (POST /forecasts via API Gateway):
  { "course_id": "C0042", "days": 7 }

Response:
  { "course_id": "...", "forecast": [ {"date": "...", "predicted_enrollments": ...}, ... ] }
"""
import json
import os
import boto3

FORECASTING_MODEL_BUCKET = os.environ.get("FORECASTING_MODEL_BUCKET")
FORECASTING_MODEL_KEY = os.environ.get("FORECASTING_MODEL_KEY")
COURSE_EMBEDDINGS_TABLE = os.environ.get("COURSE_EMBEDDINGS_TABLE")
ENROLLMENT_HISTORY_TABLE = os.environ.get("ENROLLMENT_HISTORY_TABLE")
LEARNER_ACTIVITIES_TABLE = os.environ.get("LEARNER_ACTIVITIES_TABLE")

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

_model = None


def load_model():
    global _model
    if _model is None:
        # TODO: download & unpickle model dari S3
        raise NotImplementedError("TODO: implement load_model()")
    return _model


def get_enrollment_history(course_id):
    # TODO: query DynamoDB table ENROLLMENT_HISTORY_TABLE
    raise NotImplementedError


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        course_id = body["course_id"]
        days = int(body.get("days", 7))

        # model = load_model()
        # history = get_enrollment_history(course_id)
        # forecast = model.predict(history, days)  # TODO

        forecast = []  # TODO: list of {"date": ..., "predicted_enrollments": ...}

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"course_id": course_id, "forecast": forecast}),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
