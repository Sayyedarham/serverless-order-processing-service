from typing import Any

from common.config import logger
from common.dynamo import get_or_create_fulfillment


class DownstreamServiceError(Exception):
    pass


class DownstreamTransientError(DownstreamServiceError):
    pass


class DownstreamPermanentError(DownstreamServiceError):
    pass


def call_downstream_fulfillment(order_id: str, fulfillment_key: str) -> dict[str, Any]:
    """Run a bounded deterministic simulation and return its idempotent result."""
    result = {
        "status": "APPROVED",
        "authorization_code": f"AUTH-{order_id[:8].upper()}",
        "fulfillment_key": fulfillment_key,
    }
    saved_result = get_or_create_fulfillment(fulfillment_key, result)
    logger.info(
        "Simulated fulfillment completed",
        extra={"order_id": order_id, "fulfillment_key": fulfillment_key},
    )
    return saved_result
