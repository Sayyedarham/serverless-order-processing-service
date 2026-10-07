from typing import Any

import pytest

from worker.downstream import call_downstream_fulfillment


@pytest.mark.unit
def test_fulfillment_replay_returns_saved_result_once(setup_dynamodb: Any) -> None:
    key = "order-1:FULFILLMENT"
    first = call_downstream_fulfillment("order-1", key)
    second = call_downstream_fulfillment("order-1", key)

    assert first == second
    assert first["fulfillment_key"] == key
    operations = setup_dynamodb.scan(
        FilterExpression="#operation = :fulfillment",
        ExpressionAttributeNames={"#operation": "operation"},
        ExpressionAttributeValues={":fulfillment": "FULFILLMENT"},
    )["Items"]
    assert len(operations) == 1
