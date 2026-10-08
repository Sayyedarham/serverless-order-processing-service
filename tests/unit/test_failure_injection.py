import pytest

from common.dynamo import get_order, put_order_if_not_exists
from common.failure_injection import consume_failure_injection, create_failure_injection
from common.models import OrderRecord, OrderStatus
from worker.downstream import DownstreamTransientError, call_downstream_fulfillment
from worker.handler import lambda_handler


@pytest.mark.unit
def test_failure_injection_is_scoped_bounded_and_consumed(setup_dynamodb: object) -> None:
    create_failure_injection("run-1", "scenario-1", "WORKER", max_requests=2)

    assert consume_failure_injection("run-1", "scenario-1", "WORKER") == 0
    assert consume_failure_injection("run-1", "scenario-1", "WORKER") == 0
    assert consume_failure_injection("run-1", "scenario-1", "WORKER") is None
    assert consume_failure_injection(None, "scenario-1", "WORKER") is None


@pytest.mark.unit
def test_failure_injection_rejects_unbounded_values(setup_dynamodb: object) -> None:
    with pytest.raises(ValueError, match="max_requests"):
        create_failure_injection("run-1", "scenario-1", "WORKER", max_requests=4)
    with pytest.raises(ValueError, match="expiry"):
        create_failure_injection("run-1", "scenario-1", "FULFILLMENT_DELAY", ttl_seconds=901)


@pytest.mark.unit
def test_fulfillment_failure_token_fails_once(setup_dynamodb: object) -> None:
    create_failure_injection("run-2", "scenario-2", "FULFILLMENT_FAIL")

    with pytest.raises(DownstreamTransientError, match="verification-injected"):
        call_downstream_fulfillment("order-1", "order-1:FULFILLMENT", "run-2", "scenario-2")
    assert call_downstream_fulfillment("order-1", "order-1:FULFILLMENT", "run-2", "scenario-2")


@pytest.mark.unit
def test_worker_failure_token_is_limited_to_the_verification_message(
    setup_dynamodb: object, lambda_context: object
) -> None:
    order_id = "verification-order"
    put_order_if_not_exists(
        OrderRecord(
            orderId=order_id,
            idempotencyKey="idem-verification-order",
            customerId="customer-1",
            status=OrderStatus.RECEIVED,
            items=[],
            totalAmount=0,
            createdAt="2026-10-08T00:00:00Z",
            updatedAt="2026-10-08T00:00:00Z",
            expiresAt=1800000000,
        )
    )
    create_failure_injection("run-3", "scenario-3", "WORKER")
    event = {
        "Records": [
            {
                "messageId": "message-1",
                "body": (
                    '{"orderId":"verification-order","idempotencyKey":"idem-verification-order",'
                    '"verificationRunId":"run-3","scenarioId":"scenario-3"}'
                ),
            }
        ]
    }

    assert lambda_handler(event, lambda_context) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}]
    }
    assert get_order(order_id)["status"] == OrderStatus.PROCESSING.value  # type: ignore[index]
