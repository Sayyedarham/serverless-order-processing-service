"""Internal-only, TTL-bound failure tokens for verification jobs."""

import time
from typing import Any

from botocore.exceptions import ClientError

from common.dynamo import get_orders_table

_ACTIONS = {"WORKER", "FULFILLMENT_FAIL", "FULFILLMENT_DELAY"}
_MAX_AFFECTED_REQUESTS = 3
_MAX_DELAY_SECONDS = 3


def _key(run_id: str, scenario_id: str, action: str) -> str:
    return f"FAILURE_INJECTION#{run_id}#{scenario_id}#{action}"


def create_failure_injection(
    run_id: str,
    scenario_id: str,
    action: str,
    *,
    max_requests: int = 1,
    ttl_seconds: int = 300,
    delay_seconds: int = 0,
) -> None:
    """Create one verification-only token. This is deliberately not an HTTP API."""
    if not run_id or not scenario_id or action not in _ACTIONS:
        raise ValueError("invalid verification failure injection")
    if not 1 <= max_requests <= _MAX_AFFECTED_REQUESTS:
        raise ValueError(f"max_requests must be 1..{_MAX_AFFECTED_REQUESTS}")
    if not 1 <= ttl_seconds <= 900 or not 0 <= delay_seconds <= _MAX_DELAY_SECONDS:
        raise ValueError("invalid failure injection expiry or delay")
    get_orders_table().put_item(
        Item={
            "orderId": _key(run_id, scenario_id, action),
            "operation": "FAILURE_INJECTION",
            "remaining": max_requests,
            "delaySeconds": delay_seconds,
            "expiresAt": int(time.time()) + ttl_seconds,
        },
        ConditionExpression="attribute_not_exists(orderId)",
    )


def consume_failure_injection(
    run_id: str | None, scenario_id: str | None, action: str
) -> int | None:
    """Atomically consume one token and return its delay, or None when disabled."""
    if not run_id or not scenario_id or action not in _ACTIONS:
        return None
    try:
        response: dict[str, Any] = get_orders_table().update_item(
            Key={"orderId": _key(run_id, scenario_id, action)},
            UpdateExpression="SET remaining = remaining - :one",
            ConditionExpression="remaining > :zero AND expiresAt > :now",
            ExpressionAttributeValues={":one": 1, ":zero": 0, ":now": int(time.time())},
            ReturnValues="ALL_NEW",
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return None
        raise
    return int(response.get("Attributes", {}).get("delaySeconds", 0))
