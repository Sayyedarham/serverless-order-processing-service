from typing import Any

import pytest

from worker.downstream import (
    DownstreamPermanentError,
    DownstreamTransientError,
    call_downstream_fulfillment,
)


@pytest.mark.unit
def test_fulfillment_replay_returns_saved_result_once(setup_dynamodb: Any) -> None:
    key = "order-1:FULFILLMENT"
    order = {"customerId": "cust-1"}

    first = call_downstream_fulfillment("order-1", key, order)
    second = call_downstream_fulfillment("order-1", key, order)

    assert first == second
    assert first["fulfillment_key"] == key
    operations = setup_dynamodb.scan(
        FilterExpression="#operation = :fulfillment",
        ExpressionAttributeNames={"#operation": "operation"},
        ExpressionAttributeValues={":fulfillment": "FULFILLMENT"},
    )["Items"]
    assert len(operations) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("customer_id", "error_type"),
    [
        ("sim-timeout", DownstreamTransientError),
        ("sim-fail", DownstreamPermanentError),
    ],
)
def test_fulfillment_failure_modes(customer_id: str, error_type: type[Exception]) -> None:
    with pytest.raises(error_type):
        call_downstream_fulfillment("order-2", "order-2:FULFILLMENT", {"customerId": customer_id})


@pytest.mark.unit
def test_fulfillment_delay_mode_succeeds(setup_dynamodb: Any) -> None:
    result = call_downstream_fulfillment(
        "order-3", "order-3:FULFILLMENT", {"customerId": "sim-delay"}
    )
    assert result["status"] == "APPROVED"
