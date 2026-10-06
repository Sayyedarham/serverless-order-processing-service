"""DynamoDB helper client with conditional writes and idempotency guarantees."""

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
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [float_to_decimal(i) for i in obj]
    return obj


def decimal_to_float(obj: Any) -> Any:
    """Recursively convert Decimal values back to float/int for JSON responses."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


class IdempotencyConflictError(Exception):
    """Raised when an orderId exists with a different idempotency key."""

    pass


def put_order_if_not_exists(record: OrderRecord) -> tuple[bool, dict[str, Any]]:
    """
    Conditionally insert a new order record if orderId does not already exist.

    Returns:
        (is_new, record_data):
        - (True, record_data) if newly created.
        - (False, existing_record) if idempotent duplicate with matching idempotencyKey.

    Raises:
        IdempotencyConflictError: If orderId exists but idempotencyKey differs.
    """
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
            if existing and existing.get("idempotencyKey") == record.idempotencyKey:
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
    """Update order status and timestamp in DynamoDB."""
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

    response = table.update_item(
        Key={"orderId": order_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=float_to_decimal(expr_attr_values),
        ReturnValues="ALL_NEW",
    )
    attributes = response.get("Attributes", {})
    return decimal_to_float(attributes)  # type: ignore[no-any-return]


def get_order(order_id: str) -> dict[str, Any] | None:
    """Retrieve an order by ID from DynamoDB."""
    table = get_orders_table()
    response = table.get_item(Key={"orderId": order_id})
    item = response.get("Item")
    if not item:
        return None
    return decimal_to_float(item)  # type: ignore[no-any-return]
