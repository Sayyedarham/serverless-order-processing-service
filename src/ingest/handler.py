"""Ingest Lambda Handler for POST /orders."""

import json
import time
import uuid
from typing import Any

from aws_lambda_powertools.metrics import MetricUnit
from pydantic import ValidationError

from common.config import SERVICE_KEY, TTL_DAYS, logger, metrics, tracer
from common.dynamo import IdempotencyConflictError, put_order_if_not_exists
from common.models import OrderCreateRequest, OrderRecord, OrderStatus
from common.sqs import send_order_message

MAX_PAYLOAD_BYTES = 10 * 1024  # 10 KB limit to prevent abuse


def build_response(
    status_code: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Idempotency-Key,X-Service-Key",
    }
    if headers:
        default_headers.update(headers)
    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body),
    }


@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    # Handle preflight CORS request
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "")
    ).upper()

    if http_method == "OPTIONS":
        return build_response(204, {})

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    # 1. Shared secret authentication check (if configured)
    if SERVICE_KEY:
        client_key = headers.get("x-service-key")
        if not client_key or client_key != SERVICE_KEY:
            logger.warning("Unauthorized access attempt: invalid or missing X-Service-Key")
            return build_response(
                401, {"error": "Unauthorized", "message": "Invalid or missing X-Service-Key"}
            )

    # 2. Idempotency Key validation
    idempotency_key = headers.get("idempotency-key", "").strip()
    if not idempotency_key:
        logger.warning("Rejected request missing Idempotency-Key header")
        return build_response(
            400,
            {
                "error": "Bad Request",
                "message": "Missing required 'Idempotency-Key' header",
            },
        )

    # 3. Payload size check
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    if len(raw_body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        logger.warning(
            "Payload exceeds maximum size limit", extra={"bytes": len(raw_body.encode("utf-8"))}
        )
        return build_response(
            413,
            {
                "error": "Payload Too Large",
                "message": f"Request body must not exceed {MAX_PAYLOAD_BYTES} bytes",
            },
        )

    # 4. Pydantic payload parsing & validation
    try:
        body_dict = json.loads(raw_body) if raw_body else {}
        order_req = OrderCreateRequest(**body_dict)
    except (json.JSONDecodeError, ValidationError) as err:
        logger.warning("Validation error in order payload", extra={"error": str(err)})
        return build_response(
            422,
            {
                "error": "Unprocessable Entity",
                "message": "Invalid order payload schema",
                "details": str(err),
            },
        )

    # Deterministic orderId based on idempotency key
    order_id = str(uuid.uuid5(uuid.NAMESPACE_OID, idempotency_key))
    logger.append_keys(order_id=order_id, idempotency_key=idempotency_key)

    total_amount = (
        order_req.total_amount
        if order_req.total_amount is not None
        else order_req.calculate_total()
    )
    now_epoch = int(time.time())
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch))
    expires_at = now_epoch + (TTL_DAYS * 86400)

    record = OrderRecord(
        orderId=order_id,
        idempotencyKey=idempotency_key,
        customerId=order_req.customer_id,
        status=OrderStatus.RECEIVED,
        items=[item.model_dump() for item in order_req.items],
        totalAmount=total_amount,
        createdAt=now_iso,
        updatedAt=now_iso,
        expiresAt=expires_at,
    )

    # 5. Conditional put into DynamoDB (idempotent write)
    try:
        is_new, saved_record = put_order_if_not_exists(record)
    except IdempotencyConflictError as err:
        logger.error("Idempotency conflict error", extra={"error": str(err)})
        return build_response(
            409,
            {"error": "Conflict", "message": str(err)},
        )

    # 6. Publish to SQS only if this is a newly accepted order
    if is_new:
        send_order_message(
            order_id=order_id,
            idempotency_key=idempotency_key,
            payload=order_req.model_dump(),
        )
        metrics.add_metric(name="OrdersReceived", unit=MetricUnit.Count, value=1)
        logger.info("Order accepted and queued", extra={"order_id": order_id})
        status_code = 202
        response_msg = "Order accepted for processing"
    else:
        logger.info("Duplicate idempotent order replay returned", extra={"order_id": order_id})
        status_code = 200
        response_msg = "Order already accepted (idempotent replay)"

    return build_response(
        status_code,
        {
            "orderId": order_id,
            "status": saved_record.get("status", OrderStatus.RECEIVED.value),
            "message": response_msg,
            "createdAt": saved_record.get("createdAt"),
        },
    )
