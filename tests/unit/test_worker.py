import json
from typing import Any

import pytest

from common.dynamo import get_order, put_order_if_not_exists
from common.models import OrderRecord, OrderStatus
from worker.handler import lambda_handler


def create_sample_order(
    order_id: str, status: OrderStatus = OrderStatus.RECEIVED, customer_id: str = "cust-1"
) -> None:
    record = OrderRecord(
        orderId=order_id,
        idempotencyKey=f"idem-{order_id}",
        customerId=customer_id,
        status=status,
        items=[{"item_id": "i1", "name": "Test Item", "quantity": 1, "price": 20.0}],
        totalAmount=20.0,
        createdAt="2026-10-06T00:00:00Z",
        updatedAt="2026-10-06T00:00:00Z",
        expiresAt=1800000000,
    )
    put_order_if_not_exists(record)


@pytest.mark.unit
def test_worker_empty_batch(lambda_context: Any) -> None:
    event: dict[str, Any] = {"Records": []}
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": []}


@pytest.mark.unit
def test_worker_missing_order_id(lambda_context: Any) -> None:
    event = {
        "Records": [
            {
                "messageId": "msg-no-order-id",
                "body": json.dumps({"payload": {}}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": []}


@pytest.mark.unit
def test_worker_order_already_completed_idempotency(
    setup_dynamodb: Any, lambda_context: Any
) -> None:
    order_id = "order-already-done"
    create_sample_order(order_id, status=OrderStatus.COMPLETED)

    event = {
        "Records": [
            {
                "messageId": "msg-done-1",
                "body": json.dumps({"orderId": order_id, "idempotencyKey": "idem-1"}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": []}

    order = get_order(order_id)
    assert order is not None
    assert order["status"] == OrderStatus.COMPLETED.value


@pytest.mark.unit
def test_worker_successful_processing(setup_dynamodb: Any, lambda_context: Any) -> None:
    order_id = "order-success-1"
    create_sample_order(order_id, status=OrderStatus.RECEIVED)

    event = {
        "Records": [
            {
                "messageId": "msg-success-1",
                "body": json.dumps({"orderId": order_id, "idempotencyKey": "idem-success"}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": []}

    order = get_order(order_id)
    assert order is not None
    assert order["status"] == OrderStatus.COMPLETED.value


@pytest.mark.unit
def test_worker_transient_failure_reports_partial_batch_item(
    setup_dynamodb: Any, lambda_context: Any
) -> None:
    order_id = "order-transient-1"
    create_sample_order(order_id, status=OrderStatus.RECEIVED, customer_id="sim-fail-transient")

    event = {
        "Records": [
            {
                "messageId": "msg-transient-fail",
                "body": json.dumps({"orderId": order_id, "idempotencyKey": "idem-fail"}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-transient-fail"}]}


@pytest.mark.unit
def test_worker_permanent_failure_marks_order_failed(
    setup_dynamodb: Any, lambda_context: Any
) -> None:
    order_id = "order-perm-1"
    create_sample_order(order_id, status=OrderStatus.RECEIVED, customer_id="sim-fail-permanent")

    event = {
        "Records": [
            {
                "messageId": "msg-perm-fail",
                "body": json.dumps({"orderId": order_id, "idempotencyKey": "idem-perm"}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": []}

    order = get_order(order_id)
    assert order is not None
    assert order["status"] == OrderStatus.FAILED.value
    assert "Simulated fatal validation failure" in order.get("errorMessage", "")


@pytest.mark.unit
def test_worker_order_not_found_in_dynamo(setup_dynamodb: Any, lambda_context: Any) -> None:
    event = {
        "Records": [
            {
                "messageId": "msg-not-found",
                "body": json.dumps({"orderId": "non-existent-order-id"}),
            }
        ]
    }
    result = lambda_handler(event, lambda_context)
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-not-found"}]}
