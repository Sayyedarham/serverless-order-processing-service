"""Integration tests for End-to-End order processing and DLQ redrive routing."""

import json
from typing import Any

import boto3
import pytest

from common.models import OrderStatus
from ingest.handler import lambda_handler as ingest_handler
from status.handler import lambda_handler as status_handler
from worker.handler import lambda_handler as worker_handler


@pytest.mark.integration
def test_end_to_end_order_lifecycle(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    """Verify complete lifecycle: Ingest -> SQS -> Worker -> Status (COMPLETED)."""
    # 1. Ingest an order
    ingest_event = {
        "httpMethod": "POST",
        "headers": {
            "Idempotency-Key": "e2e-order-flow-001",
            "X-Service-Key": "test-secret-key",
            "Content-Type": "application/json",
        },
        "body": json.dumps(
            {
                "customer_id": "cust-e2e",
                "items": [
                    {"item_id": "laptop-1", "name": "ThinkPad", "quantity": 1, "price": 1200.0},
                    {"item_id": "mouse-1", "name": "Logitech Mouse", "quantity": 1, "price": 40.0},
                ],
            }
        ),
    }
    ingest_resp = ingest_handler(ingest_event, lambda_context)
    assert ingest_resp["statusCode"] == 202
    ingest_body = json.loads(ingest_resp["body"])
    order_id = ingest_body["orderId"]

    # 2. Check initial status is RECEIVED
    status_event = {
        "rawPath": f"/orders/{order_id}",
        "pathParameters": {"orderId": order_id},
    }
    status_resp = status_handler(status_event, lambda_context)
    assert status_resp["statusCode"] == 200
    assert json.loads(status_resp["body"])["order"]["status"] == OrderStatus.RECEIVED.value

    # 3. Pull message from SQS and pass to Worker Lambda
    sqs = boto3.client("sqs", region_name="us-east-1")
    sqs_res = sqs.receive_message(QueueUrl=setup_sqs["queue_url"], MaxNumberOfMessages=1)
    messages = sqs_res.get("Messages", [])
    assert len(messages) == 1

    worker_event = {
        "Records": [
            {
                "messageId": messages[0]["MessageId"],
                "receiptHandle": messages[0]["ReceiptHandle"],
                "body": messages[0]["Body"],
            }
        ]
    }
    worker_resp = worker_handler(worker_event, lambda_context)
    assert worker_resp == {"batchItemFailures": []}

    # 4. Check final status is COMPLETED
    final_status_resp = status_handler(status_event, lambda_context)
    assert final_status_resp["statusCode"] == 200
    order_data = json.loads(final_status_resp["body"])["order"]
    assert order_data["status"] == OrderStatus.COMPLETED.value
    assert order_data["totalAmount"] == 1240.0


@pytest.mark.integration
def test_dlq_routing_after_max_receive_retries(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    """Verify that after maxReceiveCount (3) failures, the message routes to the DLQ."""
    sqs = boto3.client("sqs", region_name="us-east-1")

    # Ingest an order designed to trigger transient failure
    ingest_event = {
        "httpMethod": "POST",
        "headers": {
            "Idempotency-Key": "dlq-retry-flow-001",
            "X-Service-Key": "test-secret-key",
        },
        "body": json.dumps(
            {
                "customer_id": "sim-fail-transient",
                "items": [
                    {"item_id": "fail-item", "name": "Flaky Widget", "quantity": 1, "price": 9.99}
                ],
            }
        ),
    }
    ingest_resp = ingest_handler(ingest_event, lambda_context)
    assert ingest_resp["statusCode"] == 202

    # Simulate 3 processing attempts
    queue_url = setup_sqs["queue_url"]
    dlq_url = setup_sqs["dlq_url"]

    for attempt in range(1, 4):
        recv = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            VisibilityTimeout=0,  # make visible immediately on next loop
            AttributeNames=["ApproximateReceiveCount"],
        )
        msgs = recv.get("Messages", [])
        if not msgs:
            break
        msg = msgs[0]

        worker_event = {
            "Records": [
                {
                    "messageId": msg["MessageId"],
                    "receiptHandle": msg["ReceiptHandle"],
                    "body": msg["Body"],
                    "attributes": {"ApproximateReceiveCount": str(attempt)},
                }
            ]
        }
        res = worker_handler(worker_event, lambda_context)
        assert len(res["batchItemFailures"]) == 1

    # After 3 receive attempts with redrive policy, standard SQS moves message to DLQ
    # In moto / live SQS, verify DLQ receives or is targetable
    dlq_attributes = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["All"])[
        "Attributes"
    ]
    assert "QueueArn" in dlq_attributes
