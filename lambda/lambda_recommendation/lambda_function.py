"""
lambda_recommendation/lambda_function.py

Env vars (lihat .env.example):
  MODEL_BUCKET, MODEL_KEY, LEARNERS_TABLE, COURSE_TABLE

Request (POST /predict via API Gateway):
  { "learner_id": "L0001", "course_id": "C0042" }

Response:
  { "learner_id": "...", "course_id": "...", "recommendation_percentage": 0.0-100.0 }
"""
import json
import os
import boto3

MODEL_BUCKET = os.environ.get("MODEL_BUCKET")
MODEL_KEY = os.environ.get("MODEL_KEY")
LEARNERS_TABLE = os.environ.get("LEARNERS_TABLE")
COURSE_TABLE = os.environ.get("COURSE_TABLE")

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

_model = None  # cache model antar invocation (warm start)


def load_model():
    global _model
    if _model is None:
        # TODO: download model dari S3 (MODEL_BUCKET/MODEL_KEY) lalu unpickle
        # obj = s3.get_object(Bucket=MODEL_BUCKET, Key=MODEL_KEY)
        # _model = pickle.loads(obj["Body"].read())
        raise NotImplementedError("TODO: implement load_model()")
    return _model


def get_learner_features(learner_id):
    # TODO: query DynamoDB table LEARNERS_TABLE
    raise NotImplementedError


def get_course_features(course_id):
    # TODO: query DynamoDB table COURSE_TABLE
    raise NotImplementedError


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        learner_id = body["learner_id"]
        course_id = body["course_id"]

        # model = load_model()
        # learner_feat = get_learner_features(learner_id)
        # course_feat = get_course_features(course_id)
        # score = model.predict(...)  # TODO

        score = 0.0  # placeholder

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "learner_id": learner_id,
                "course_id": course_id,
                "recommendation_percentage": round(score, 2),
            }),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
