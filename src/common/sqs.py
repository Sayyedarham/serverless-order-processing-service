import json
from typing import Any

import boto3

from common.config import QUEUE_URL, logger

_sqs_client = None


def get_sqs_client() -> Any:
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
    return _sqs_client


def send_order_message(
    order_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
    correlation_id: str,
    verification_run_id: str | None = None,
    scenario_id: str | None = None,
) -> str:
    client = get_sqs_client()
    body = {
        "orderId": order_id,
        "idempotencyKey": idempotency_key,
        "payload": payload,
        "correlationId": correlation_id,
    }
    if verification_run_id and scenario_id:
        body["verificationRunId"] = verification_run_id
        body["scenarioId"] = scenario_id

    message_attributes = {
        "OrderId": {
            "DataType": "String",
            "StringValue": order_id,
        },
        "IdempotencyKey": {
            "DataType": "String",
            "StringValue": idempotency_key,
        },
        "CorrelationId": {"DataType": "String", "StringValue": correlation_id},
    }

    response = client.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(body),
        MessageAttributes=message_attributes,
    )

    msg_id = response.get("MessageId", "")
    logger.info(
        "Published order to SQS",
        extra={"order_id": order_id, "correlation_id": correlation_id, "sqs_message_id": msg_id},
    )
    return str(msg_id)
