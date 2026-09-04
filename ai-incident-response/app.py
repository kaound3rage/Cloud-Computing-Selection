"""
ai-incident-response/app.py

FastAPI webhook service untuk Automated Incident Response (EduPintar).

Endpoint: POST /webhook
  1. Jika message SNS bertipe "SubscriptionConfirmation" -> GET ke SubscribeURL.
  2. Jika message SNS bertipe "Notification":
       - ekstrak AlarmName dari body
       - ambil 5 log error terbaru dari CloudWatch Logs (filter "ERROR", 1 jam terakhir)
       - kirim log ke LLM untuk membuat Summary + Solusi
       - publish hasilnya ke SNS_TOPIC_ARN dengan subject:
         "Incident Report Summary: [AlarmName]"

Env vars (lihat .env.example):
  LLM_PROVIDER, OLLAMA_ENDPOINT, OLLAMA_MODEL, GROQ_API_KEY, GROQ_MODEL,
  SNS_TOPIC_ARN, LIST_SNS_TOPIC_ARN, AWS_REGION,
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, PORT
"""
import json
import logging
import os
import time
from typing import Optional

import boto3
import httpx
from fastapi import FastAPI, Request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ai-incident-response")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").lower()
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-8b-8192")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

try:
    LIST_SNS_TOPIC_ARN: dict = json.loads(os.environ.get("LIST_SNS_TOPIC_ARN", "{}"))
except json.JSONDecodeError:
    logger.warning("LIST_SNS_TOPIC_ARN is not valid JSON; using empty mapping")
    LIST_SNS_TOPIC_ARN = {}

LOG_LOOKBACK_HOURS = 1
MAX_LOG_EVENTS = 5
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
LLM_TIMEOUT = 20

boto3_session = boto3.Session()
sns_client = boto3_session.client("sns", region_name=AWS_REGION)
logs_client = boto3_session.client("logs", region_name=AWS_REGION)

# Cache for expensive resources
_llm_client: Optional[httpx.AsyncClient] = None


def get_llm_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient for LLM calls."""
    global _llm_client
    if _llm_client is None or _llm_client.is_closed:
        _llm_client = httpx.AsyncClient(timeout=LLM_TIMEOUT)
    return _llm_client


async def confirm_subscription(subscribe_url: str) -> int:
    """Confirm SNS subscription by GETting the confirmation URL."""
    if not subscribe_url:
        raise ValueError("SubscriptionConfirmation missing SubscribeURL")
    logger.info("Confirming SNS subscription: %s", subscribe_url)
    async with httpx.AsyncClient() as client:
        resp = await client.get(subscribe_url)
    logger.info("Subscription confirmation status: %s", resp.status_code)
    return resp.status_code


def get_recent_error_logs(log_group: str, limit: int = MAX_LOG_EVENTS) -> list[str]:
    """Query CloudWatch Logs for recent ERROR events in a log group."""
    if not log_group:
        return []

    start_time_ms = int((time.time() - LOG_LOOKBACK_HOURS * 3600) * 1000)
    end_time_ms = int(time.time() * 1000)

    logger.info(
        "Querying logs for group=%s window_ms=%d..%d",
        log_group, start_time_ms, end_time_ms,
    )

    try:
        response = logs_client.filter_log_events(
            logGroupName=log_group,
            filterPattern="ERROR",
            startTime=start_time_ms,
            endTime=end_time_ms,
            limit=limit,
        )
    except logs_client.exceptions.ResourceNotFoundException:
        logger.warning("Log group %s not found", log_group)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("CloudWatch Logs query failed: %s", exc)
        return []

    events = response.get("events", [])
    logs = [event.get("message", "") for event in events[:limit]]
    logger.info("Found %d error log events", len(logs))
    return logs


async def summarize_with_llm(logs: list[str]) -> dict:
    """Send logs to the configured LLM and return {summary, solution}."""
    if not logs:
        return {"summary": "No error logs found.", "solution": "No action needed."}

    prompt = (
        "Sebagai DevOps, berikan 1 ringkasan penyebab error (Summary) dan "
        "1 rekomendasi (Solusi) dari semua log berikut:\n\n" + "\n".join(logs)
    )

    if LLM_PROVIDER == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        client = get_llm_client()
        resp = await client.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_llm_response(content)

    elif LLM_PROVIDER == "ollama":
        if not OLLAMA_ENDPOINT or not OLLAMA_MODEL:
            raise RuntimeError("OLLAMA_ENDPOINT and OLLAMA_MODEL must be set for ollama")
        payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
        client = get_llm_client()
        resp = await client.post(OLLAMA_ENDPOINT, json=payload)
        resp.raise_for_status()
        content = resp.json().get("response", "")
        return _parse_llm_response(content)

    raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _parse_llm_response(content: str) -> dict:
    """Extract summary and solution from an LLM response text."""
    summary = content.strip()
    solution = ""
    lower = content.lower()

    for marker in ("solusi", "solution", "rekomendasi", "fix"):
        idx = lower.find(marker)
        if idx != -1:
            summary = content[:idx].strip()
            solution = content[idx:].strip()
            break

    if not solution:
        # Fallback: take the whole response as summary
        summary = content.strip()
        solution = "Rekomendasi tidak tersedia dari model."

    return {"summary": summary, "solution": solution}


def publish_incident_report(alarm_name: str, summary: str, solution: str) -> None:
    """Publish the incident report to the SNS topic."""
    if not SNS_TOPIC_ARN:
        raise RuntimeError("SNS_TOPIC_ARN is not set")

    subject = f"Incident Report Summary: {alarm_name}"
    message = json.dumps(
        {
            "alarm_name": alarm_name,
            "summary": summary,
            "solution": solution,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        ensure_ascii=False,
    )

    logger.info("Publishing incident report to %s (alarm=%s)", SNS_TOPIC_ARN, alarm_name)
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject[:100],  # SNS subject limit is 100 chars
        Message=message,
    )


@app.post("/webhook")
async def webhook(request: Request):
    body_raw = await request.body()
    try:
        payload = json.loads(body_raw)
    except json.JSONDecodeError:
        return Response(
            status_code=400,
            content=json.dumps({"error": "Invalid JSON body"}),
            media_type="application/json",
        )

    message_type = request.headers.get("x-amz-sns-message-type")

    if message_type == "SubscriptionConfirmation":
        try:
            status = await confirm_subscription(payload["SubscribeURL"])
        except (KeyError, ValueError, httpx.HTTPError) as exc:
            logger.error("Failed to confirm subscription: %s", exc)
            return Response(status_code=500, content=json.dumps({"error": str(exc)}))
        return {"confirmed": True, "status": status}

    if message_type == "Notification":
        try:
            message = payload["Message"]
            if isinstance(message, str):
                alarm_message = json.loads(message)
            else:
                alarm_message = message
        except (KeyError, json.JSONDecodeError) as exc:
            logger.error("Invalid Notification message: %s", exc)
            return Response(status_code=400, content=json.dumps({"error": str(exc)}))

        alarm_name = alarm_message.get("AlarmName", "UnknownAlarm")
        log_group = LIST_SNS_TOPIC_ARN.get(alarm_name)

        try:
            logs = get_recent_error_logs(log_group)
            result = await summarize_with_llm(logs)
            publish_incident_report(alarm_name, result["summary"], result["solution"])
        except Exception as exc:  # noqa: BLE001
            logger.error("Incident processing failed: %s", exc, exc_info=True)
            return Response(status_code=500, content=json.dumps({"error": str(exc)}))

        return {"received": True, "alarm": alarm_name, "log_group": log_group, "report_sent": True}

    return {"ignored": True, "message_type": message_type}


@app.get("/health")
async def health():
    """Health check endpoint for load balancers / ECS."""
    return {"status": "ok", "service": "ai-incident-response"}
