import importlib
import json
from typing import Any
from unittest.mock import Mock

import boto3
import pytest

from common.dynamo import get_order, put_order_if_not_exists
from common.models import OrderRecord, OrderStatus
from worker.downstream import DownstreamPermanentError, DownstreamTransientError
from worker.handler import lambda_handler

worker_module = importlib.import_module("worker.handler")


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
def test_retry_after_fulfillment_before_completion_write(
    setup_dynamodb: Any, lambda_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id = "order-crash-after-fulfillment"
    create_sample_order(order_id)
    event = {
        "Records": [
            {
                "messageId": "msg-crash-window",
                "body": json.dumps({"orderId": order_id, "idempotencyKey": "idem-crash-window"}),
            }
        ]
    }
    real_update = worker_module.update_order_status
    failed_completion = False

    def fail_first_completion(order_id: str, status: OrderStatus, **kwargs: Any) -> Any:
        nonlocal failed_completion
        if status == OrderStatus.COMPLETED and not failed_completion:
            failed_completion = True
            raise RuntimeError("simulated worker crash after fulfillment")
        return real_update(order_id, status, **kwargs)

    monkeypatch.setattr(worker_module, "update_order_status", fail_first_completion)

    first_attempt = lambda_handler(event, lambda_context)
    assert first_attempt == {"batchItemFailures": [{"itemIdentifier": "msg-crash-window"}]}
    order = get_order(order_id)
    assert order is not None
    assert order["status"] == OrderStatus.PROCESSING

    retry_attempt = lambda_handler(event, lambda_context)
    assert retry_attempt == {"batchItemFailures": []}
    order = get_order(order_id)
    assert order is not None
    assert order["status"] == OrderStatus.COMPLETED

    operations = setup_dynamodb.scan(
        FilterExpression="#operation = :fulfillment",
        ExpressionAttributeNames={"#operation": "operation"},
        ExpressionAttributeValues={":fulfillment": "FULFILLMENT"},
    )["Items"]
    assert len(operations) == 1


@pytest.mark.unit
def test_worker_transient_failure_reports_partial_batch_item(
    setup_dynamodb: Any, lambda_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id = "order-transient-1"
    create_sample_order(order_id, status=OrderStatus.RECEIVED)
    monkeypatch.setattr(
        worker_module,
        "call_downstream_fulfillment",
        Mock(side_effect=DownstreamTransientError("injected by test")),
    )

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
def test_bounded_dlq_redrive_completes_order_after_failure_is_removed(
    setup_dynamodb: Any,
    setup_sqs: dict[str, str],
    lambda_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loadtest.redrive_dlq import redrive

    order_id = "order-dlq-redrive"
    create_sample_order(order_id)
    real_fulfillment = worker_module.call_downstream_fulfillment
    monkeypatch.setattr(
        worker_module,
        "call_downstream_fulfillment",
        Mock(side_effect=DownstreamTransientError("injected by test")),
    )
    sqs = boto3.client("sqs", region_name="us-east-1")
    body = json.dumps({"orderId": order_id, "idempotencyKey": f"idem-{order_id}"})
    for receive_count in (1, 2, 3):
        result = lambda_handler(
            {
                "Records": [
                    {
                        "messageId": f"msg-{receive_count}",
                        "body": body,
                        "attributes": {"ApproximateReceiveCount": str(receive_count)},
                    }
                ]
            },
            lambda_context,
        )
        assert result == {"batchItemFailures": [{"itemIdentifier": f"msg-{receive_count}"}]}
    assert get_order(order_id)["status"] == OrderStatus.DLQ.value  # type: ignore[index]

    sqs.send_message(QueueUrl=setup_sqs["dlq_url"], MessageBody=body)
    assert redrive(max_messages=1, operator="test-operator") == 1

    queued = sqs.receive_message(QueueUrl=setup_sqs["queue_url"], MaxNumberOfMessages=1)
    assert queued["Messages"]
    record = queued["Messages"][0]
    monkeypatch.setattr(worker_module, "call_downstream_fulfillment", real_fulfillment)
    completed = lambda_handler(
        {"Records": [{"messageId": record["MessageId"], "body": record["Body"]}]},
        lambda_context,
    )
    assert completed == {"batchItemFailures": []}
    assert get_order(order_id)["status"] == OrderStatus.COMPLETED.value  # type: ignore[index]


@pytest.mark.unit
def test_worker_permanent_failure_marks_order_failed(
    setup_dynamodb: Any, lambda_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id = "order-perm-1"
    create_sample_order(order_id, status=OrderStatus.RECEIVED)
    monkeypatch.setattr(
        worker_module,
        "call_downstream_fulfillment",
        Mock(side_effect=DownstreamPermanentError("injected by test")),
    )

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
    assert "injected by test" in order.get("errorMessage", "")


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
