"""Unit tests for Status Lambda handler."""

import json
from typing import Any

import pytest

from common.dynamo import put_order_if_not_exists
from common.models import OrderRecord, OrderStatus
from status.handler import lambda_handler


@pytest.mark.unit
def test_status_cors_preflight(lambda_context: Any) -> None:
    event = {"httpMethod": "OPTIONS", "headers": {}}
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 204


@pytest.mark.unit
def test_status_health_endpoint(lambda_context: Any) -> None:
    event = {
        "rawPath": "/health",
        "requestContext": {"http": {"method": "GET", "path": "/health"}},
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "healthy"


@pytest.mark.unit
def test_status_missing_order_id_parameter(lambda_context: Any) -> None:
    event = {
        "rawPath": "/orders/",
        "pathParameters": {},
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 400


@pytest.mark.unit
def test_status_order_not_found(setup_dynamodb: Any, lambda_context: Any) -> None:
    event = {
        "rawPath": "/orders/non-existent-id",
        "pathParameters": {"orderId": "non-existent-id"},
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert body["error"] == "Not Found"


@pytest.mark.unit
def test_status_order_found_success(setup_dynamodb: Any, lambda_context: Any) -> None:
    order_id = "test-status-order-1"
    record = OrderRecord(
        orderId=order_id,
        idempotencyKey="idem-status-1",
        customerId="cust-42",
        status=OrderStatus.COMPLETED,
        items=[{"item_id": "item-99", "name": "Monitor", "quantity": 1, "price": 299.99}],
        totalAmount=299.99,
        createdAt="2026-10-06T00:00:00Z",
        updatedAt="2026-10-06T00:01:00Z",
        expiresAt=1800000000,
    )
    put_order_if_not_exists(record)

    event = {
        "rawPath": f"/orders/{order_id}",
        "pathParameters": {"orderId": order_id},
    }
    resp = lambda_handler(event, lambda_context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["order"]["orderId"] == order_id
    assert body["order"]["status"] == "COMPLETED"
    assert body["order"]["totalAmount"] == 299.99
