import json
import time
from typing import Any

from common.config import logger, metrics, tracer
from common.dynamo import get_order


def build_response(
    status_code: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-Service-Key",
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
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "")
    ).upper()

    if http_method == "OPTIONS":
        return build_response(204, {})

    raw_path = (
        event.get("rawPath")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or event.get("path", "")
    )

    if raw_path.rstrip("/").endswith("/health"):
        return build_response(
            200,
            {
                "status": "healthy",
                "service": "order-processing-service",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )

    path_parameters = event.get("pathParameters") or {}
    order_id = path_parameters.get("orderId") or path_parameters.get("id")

    if not order_id:
        return build_response(
            400, {"error": "Bad Request", "message": "Missing orderId path parameter"}
        )

    logger.append_keys(order_id=order_id)
    order = get_order(order_id)

    if not order:
        logger.info("Order not found", extra={"order_id": order_id})
        return build_response(404, {"error": "Not Found", "message": f"Order {order_id} not found"})

    logger.info(
        "Order retrieved successfully", extra={"order_id": order_id, "status": order.get("status")}
    )
    return build_response(200, {"order": order})
