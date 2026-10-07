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


def send_order_message(order_id: str, idempotency_key: str, payload: dict[str, Any]) -> str:
    client = get_sqs_client()
    body = {
        "orderId": order_id,
        "idempotencyKey": idempotency_key,
        "payload": payload,
    }

    message_attributes = {
        "OrderId": {
            "DataType": "String",
            "StringValue": order_id,
        },
        "IdempotencyKey": {
            "DataType": "String",
            "StringValue": idempotency_key,
        },
    }

    response = client.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(body),
        MessageAttributes=message_attributes,
    )

    msg_id = response.get("MessageId", "")
    logger.info("Published order to SQS", extra={"order_id": order_id, "sqs_message_id": msg_id})
    return str(msg_id)
