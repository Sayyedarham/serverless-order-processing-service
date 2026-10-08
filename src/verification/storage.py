"""DynamoDB persistence for bounded verification runs."""

import time
from datetime import UTC, datetime
from typing import Any, cast

from common.dynamo import decimal_to_float, float_to_decimal, get_orders_table

RUN_PREFIX = "VERIFICATION#"
TTL_SECONDS = 7 * 86400


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_key(run_id: str) -> str:
    return f"{RUN_PREFIX}{run_id}"


def scenario_key(run_id: str, scenario_id: str) -> str:
    return f"{run_key(run_id)}#SCENARIO#{scenario_id}"


def create_run(run_id: str, scenarios: list[str]) -> dict[str, Any]:
    now = _now()
    item: dict[str, Any] = {
        "orderId": run_key(run_id),
        "operation": "VERIFICATION_RUN",
        "runId": run_id,
        "status": "QUEUED",
        "scenarios": scenarios,
        "createdAt": now,
        "updatedAt": now,
        "expiresAt": int(time.time()) + TTL_SECONDS,
    }
    get_orders_table().put_item(Item=item, ConditionExpression="attribute_not_exists(orderId)")
    return item


def get_run(run_id: str) -> dict[str, Any] | None:
    item = get_orders_table().get_item(Key={"orderId": run_key(run_id)}).get("Item")
    return decimal_to_float(item) if item else None


def set_run_status(run_id: str, status: str, error: str | None = None) -> dict[str, Any]:
    values: dict[str, Any] = {":status": status, ":updated": _now()}
    expression = "SET #status = :status, updatedAt = :updated"
    names = {"#status": "status"}
    if error is not None:
        expression += ", #error = :error"
        names["#error"] = "error"
        values[":error"] = error[:1000]
    response = get_orders_table().update_item(
        Key={"orderId": run_key(run_id)},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=float_to_decimal(values),
        ConditionExpression="attribute_exists(orderId)",
        ReturnValues="ALL_NEW",
    )
    return cast(dict[str, Any], decimal_to_float(response["Attributes"]))


def put_scenario_result(run_id: str, scenario_id: str, result: dict[str, Any]) -> None:
    item = {
        "orderId": scenario_key(run_id, scenario_id),
        "operation": "VERIFICATION_SCENARIO",
        "runId": run_id,
        "scenarioId": scenario_id,
        "expiresAt": int(time.time()) + TTL_SECONDS,
        **result,
    }
    get_orders_table().put_item(Item=float_to_decimal(item))


def get_scenario_results(run_id: str) -> list[dict[str, Any]]:
    run = get_run(run_id)
    if not run:
        return []
    table = get_orders_table()
    results = []
    for scenario_id in run.get("scenarios", []):
        item = table.get_item(Key={"orderId": scenario_key(run_id, scenario_id)}).get("Item")
        if item:
            results.append(decimal_to_float(item))
    return results
