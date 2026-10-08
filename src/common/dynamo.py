import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.config import TABLE_NAME, logger
from common.models import OrderRecord, OrderStatus

_dynamo_resource = None


def get_dynamo_resource() -> Any:
    global _dynamo_resource
    if _dynamo_resource is None:
        _dynamo_resource = boto3.resource("dynamodb")
    return _dynamo_resource


def get_orders_table() -> Any:
    return get_dynamo_resource().Table(TABLE_NAME)


def float_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj


def decimal_to_float(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


class IdempotencyConflictError(Exception):
    pass


class InvalidStateTransitionError(Exception):
    pass


def put_order_if_not_exists(record: OrderRecord) -> tuple[bool, dict[str, Any]]:
    table = get_orders_table()
    item_dict = record.model_dump()
    item_for_dynamo = float_to_decimal(item_dict)

    try:
        table.put_item(
            Item=item_for_dynamo,
            ConditionExpression="attribute_not_exists(orderId)",
        )
        logger.info("Order conditionally inserted", extra={"order_id": record.orderId})
        return True, item_dict
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.warning(
                "Conditional check failed for orderId, verifying idempotency key",
                extra={"order_id": record.orderId, "idempotency_key": record.idempotencyKey},
            )
            existing = get_order(record.orderId)
            same_request = existing and all(
                existing.get(field) == item_dict[field]
                for field in ("customerId", "items", "totalAmount")
            )
            if (
                existing
                and existing.get("idempotencyKey") == record.idempotencyKey
                and same_request
            ):
                logger.info(
                    "Idempotent duplicate order request detected",
                    extra={"order_id": record.orderId},
                )
                return False, existing
            raise IdempotencyConflictError(
                f"Order ID {record.orderId} already exists with a different idempotency key"
            ) from err
        raise


def update_order_status(
    order_id: str,
    status: OrderStatus,
    error_message: str | None = None,
    processed_by: str | None = None,
) -> dict[str, Any]:
    table = get_orders_table()
    now_iso = datetime.now(UTC).isoformat()

    update_expr = "SET #s = :status, #u = :updated_at"
    expr_attr_names = {"#s": "status", "#u": "updatedAt"}
    expr_attr_values: dict[str, Any] = {
        ":status": status.value,
        ":updated_at": now_iso,
    }

    if error_message is not None:
        update_expr += ", #e = :error_message"
        expr_attr_names["#e"] = "errorMessage"
        expr_attr_values[":error_message"] = error_message

    if processed_by is not None:
        update_expr += ", #p = :processed_by"
        expr_attr_names["#p"] = "processedBy"
        expr_attr_values[":processed_by"] = processed_by

    allowed_previous = {
        OrderStatus.PROCESSING: [OrderStatus.RECEIVED.value, OrderStatus.PROCESSING.value],
        OrderStatus.COMPLETED: [OrderStatus.PROCESSING.value],
        OrderStatus.FAILED: [OrderStatus.PROCESSING.value],
        OrderStatus.DLQ: [OrderStatus.PROCESSING.value],
        # Explicit operator redrive resets a DLQ item for normal worker processing.
        OrderStatus.RECEIVED: [OrderStatus.DLQ.value],
    }.get(status, [])
    if not allowed_previous:
        raise InvalidStateTransitionError(f"status {status.value} cannot be set by the worker")
    allowed_placeholders = []
    for index, previous_status in enumerate(allowed_previous):
        placeholder = f":previous_{index}"
        expr_attr_values[placeholder] = previous_status
        allowed_placeholders.append(placeholder)
    try:
        response = table.update_item(
            Key={"orderId": order_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=float_to_decimal(expr_attr_values),
            ConditionExpression=(
                "attribute_exists(orderId) AND #s IN (" + ", ".join(allowed_placeholders) + ")"
            ),
            ReturnValues="ALL_NEW",
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise InvalidStateTransitionError(
                f"invalid transition to {status.value} for order {order_id}"
            ) from err
        raise
    attributes = response.get("Attributes", {})
    return decimal_to_float(attributes)  # type: ignore[no-any-return]


def mark_order_enqueued(order_id: str) -> None:
    get_orders_table().update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET enqueueStatus = :status, updatedAt = :updated_at",
        ExpressionAttributeValues={
            ":status": "ENQUEUED",
            ":updated_at": datetime.now(UTC).isoformat(),
        },
        ConditionExpression="attribute_exists(orderId)",
    )


def get_order(order_id: str) -> dict[str, Any] | None:
    table = get_orders_table()
    response = table.get_item(Key={"orderId": order_id})
    item = response.get("Item")
    if not item:
        return None
    return decimal_to_float(item)  # type: ignore[no-any-return]


def get_or_create_fulfillment(fulfillment_key: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist one successful simulated fulfillment result for safe worker retries."""
    table = get_orders_table()
    item = {
        "orderId": f"FULFILLMENT#{fulfillment_key}",
        "operation": "FULFILLMENT",
        "result": result,
        # SQS can retain a message in the source queue and DLQ for up to 18 days.
        "expiresAt": int(time.time()) + 30 * 86400,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(orderId)")
        return result
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing = table.get_item(Key={"orderId": item["orderId"]}).get("Item")
        if not existing:
            raise
        return decimal_to_float(existing["result"])  # type: ignore[no-any-return]
