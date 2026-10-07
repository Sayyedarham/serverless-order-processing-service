import base64
import json
from typing import Any

import boto3
import pytest

from common.models import OrderStatus
from ingest.handler import lambda_handler


@pytest.mark.unit
def test_ingest_cors_preflight(lambda_context: Any) -> None:
    event = {
        "httpMethod": "OPTIONS",
        "headers": {},
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 204
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


@pytest.mark.unit
def test_ingest_missing_idempotency_key(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    event = {
        "httpMethod": "POST",
        "headers": {"x-service-key": "test-secret-key"},
        "body": json.dumps(
            {
                "customer_id": "c1",
                "items": [{"item_id": "i1", "name": "Item", "quantity": 1, "price": 10.0}],
            }
        ),
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "Missing required 'Idempotency-Key'" in body["message"]


@pytest.mark.unit
def test_ingest_unauthorized_missing_service_key(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    event = {
        "httpMethod": "POST",
        "headers": {"idempotency-key": "idem-123"},
        "body": json.dumps(
            {
                "customer_id": "c1",
                "items": [{"item_id": "i1", "name": "Item", "quantity": 1, "price": 10.0}],
            }
        ),
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 401
    body = json.loads(resp["body"])
    assert body["error"] == "Unauthorized"


@pytest.mark.unit
def test_ingest_payload_too_large(setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any) -> None:
    large_payload = {
        "customer_id": "c1",
        "items": [{"item_id": "i1", "name": "A" * 12000, "quantity": 1, "price": 10.0}],
    }
    event = {
        "httpMethod": "POST",
        "headers": {"idempotency-key": "idem-large", "x-service-key": "test-secret-key"},
        "body": json.dumps(large_payload),
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 413
    body = json.loads(resp["body"])
    assert body["error"] == "Payload Too Large"


@pytest.mark.unit
def test_ingest_malformed_json_and_validation(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    event = {
        "httpMethod": "POST",
        "headers": {"idempotency-key": "idem-malformed", "x-service-key": "test-secret-key"},
        "body": "{invalid-json",
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 422
    body = json.loads(resp["body"])
    assert body["error"] == "Unprocessable Entity"


@pytest.mark.unit
def test_ingest_valid_order_success_and_sqs_published(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    order_data = {
        "customer_id": "cust-999",
        "items": [
            {"item_id": "sku-1", "name": "Keyboard", "quantity": 1, "price": 50.0},
            {"item_id": "sku-2", "name": "Mousepad", "quantity": 2, "price": 15.0},
        ],
    }
    event = {
        "httpMethod": "POST",
        "headers": {
            "Idempotency-Key": "client-request-uuid-001",
            "X-Service-Key": "test-secret-key",
            "Content-Type": "application/json",
        },
        "body": json.dumps(order_data),
    }

    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert "orderId" in body
    assert body["status"] == OrderStatus.RECEIVED.value
    assert body["message"] == "Order accepted for processing"

    sqs = boto3.client("sqs", region_name="us-east-1")
    messages = sqs.receive_message(QueueUrl=setup_sqs["queue_url"], MaxNumberOfMessages=10).get(
        "Messages", []
    )
    assert len(messages) == 1
    queued_body = json.loads(messages[0]["Body"])
    assert queued_body["orderId"] == body["orderId"]
    assert queued_body["idempotencyKey"] == "client-request-uuid-001"


@pytest.mark.unit
def test_ingest_duplicate_submission_is_idempotent(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    order_data = {
        "customer_id": "cust-idempotent",
        "items": [{"item_id": "sku-1", "name": "Headphones", "quantity": 1, "price": 100.0}],
    }
    event = {
        "httpMethod": "POST",
        "headers": {
            "Idempotency-Key": "same-idempotency-key-xyz",
            "X-Service-Key": "test-secret-key",
        },
        "body": json.dumps(order_data),
    }

    resp1 = lambda_handler(event, lambda_context)
    assert resp1["statusCode"] == 202
    body1 = json.loads(resp1["body"])

    resp2 = lambda_handler(event, lambda_context)
    assert resp2["statusCode"] == 200
    body2 = json.loads(resp2["body"])

    assert body1["orderId"] == body2["orderId"]
    assert body2["message"] == "Order already accepted (idempotent replay)"

    sqs = boto3.client("sqs", region_name="us-east-1")
    messages = sqs.receive_message(QueueUrl=setup_sqs["queue_url"], MaxNumberOfMessages=10).get(
        "Messages", []
    )
    assert len(messages) == 1


@pytest.mark.unit
def test_ingest_base64_encoded_body(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any
) -> None:
    order_data = {
        "customer_id": "cust-b64",
        "items": [{"item_id": "sku-b64", "name": "Webcam", "quantity": 1, "price": 75.0}],
    }
    encoded = base64.b64encode(json.dumps(order_data).encode("utf-8")).decode("utf-8")
    event = {
        "httpMethod": "POST",
        "headers": {"Idempotency-Key": "idem-b64-1", "X-Service-Key": "test-secret-key"},
        "body": encoded,
        "isBase64Encoded": True,
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 202
