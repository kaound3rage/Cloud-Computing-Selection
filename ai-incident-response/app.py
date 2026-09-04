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
import os

import boto3
import httpx
from fastapi import FastAPI, Request

app = FastAPI(title="ai-incident-response")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
LIST_SNS_TOPIC_ARN = json.loads(os.environ.get("LIST_SNS_TOPIC_ARN", "{}"))
AWS_REGION = os.environ.get("AWS_REGION")

sns_client = boto3.client("sns", region_name=AWS_REGION)
logs_client = boto3.client("logs", region_name=AWS_REGION)


async def confirm_subscription(subscribe_url: str):
    # TODO: lakukan HTTP GET ke subscribe_url untuk konfirmasi otomatis
    async with httpx.AsyncClient() as client:
        resp = await client.get(subscribe_url)
        return resp.status_code


def get_recent_error_logs(log_group: str, limit: int = 5):
    # TODO: query CloudWatch Logs (logs_client.filter_log_events)
    #   - filterPattern="ERROR"
    #   - startTime = now - 1 jam (epoch ms)
    #   - ambil `limit` event terbaru
    raise NotImplementedError


def summarize_with_llm(logs: list[str]) -> dict:
    """Mengembalikan {"summary": "...", "solution": "..."}"""
    prompt = (
        "Sebagai DevOps, berikan 1 ringkasan penyebab error (Summary) dan "
        "1 rekomendasi (Solusi) dari semua log berikut:\n\n" + "\n".join(logs)
    )
    if LLM_PROVIDER == "groq":
        # TODO: POST ke https://api.groq.com/openai/v1/chat/completions
        #   headers: Authorization: Bearer {GROQ_API_KEY}
        #   body: {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}]}
        raise NotImplementedError
    elif LLM_PROVIDER == "ollama":
        # TODO: POST ke OLLAMA_ENDPOINT
        #   body: {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
        raise NotImplementedError
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def publish_incident_report(alarm_name: str, summary: str, solution: str):
    subject = f"Incident Report Summary: {alarm_name}"
    message = f"Summary:\n{summary}\n\nSolusi:\n{solution}"
    # TODO: sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    raise NotImplementedError


@app.post("/webhook")
async def webhook(request: Request):
    body_raw = await request.body()
    message_type = request.headers.get("x-amz-sns-message-type")
    payload = json.loads(body_raw)

    if message_type == "SubscriptionConfirmation":
        status = await confirm_subscription(payload["SubscribeURL"])
        return {"confirmed": True, "status": status}

    if message_type == "Notification":
        alarm_message = json.loads(payload["Message"])
        alarm_name = alarm_message.get("AlarmName", "UnknownAlarm")

        log_group = LIST_SNS_TOPIC_ARN.get(alarm_name)
        # TODO:
        # logs = get_recent_error_logs(log_group)
        # result = summarize_with_llm(logs)
        # publish_incident_report(alarm_name, result["summary"], result["solution"])
        return {"received": True, "alarm": alarm_name, "log_group": log_group}

    return {"ignored": True, "message_type": message_type}
