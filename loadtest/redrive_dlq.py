"""Explicitly redrive a bounded number of DLQ messages after fixing the cause."""

import argparse
import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

from common.dynamo import get_order, update_order_status
from common.models import OrderStatus

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("dlq-redrive")


def redrive(max_messages: int, operator: str) -> int:
    if not 1 <= max_messages <= 100:
        raise ValueError("max_messages must be between 1 and 100")
    if not operator.strip():
        raise ValueError("operator is required for audit logging")

    dlq_url = os.environ["ORDERS_DLQ_URL"]
    queue_url = os.environ["ORDERS_QUEUE_URL"]
    sqs = boto3.client("sqs")
    run_id = str(uuid.uuid4())
    moved = 0

    while moved < max_messages:
        response = sqs.receive_message(
            QueueUrl=dlq_url, MaxNumberOfMessages=min(10, max_messages - moved),
            WaitTimeSeconds=1, AttributeNames=["All"], MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        if not messages:
            break

        for message in messages:
            try:
                body = json.loads(message["Body"])
                order_id = body["orderId"]
                order = get_order(order_id)
                if not order or order.get("status") not in {
                    OrderStatus.DLQ.value, OrderStatus.RECEIVED.value
                }:
                    logger.warning(json.dumps({"event": "redrive_skipped", "run_id": run_id,
                                              "operator": operator, "order_id": order_id,
                                              "reason": "order missing or not eligible"}))
                    continue

                update_order_status(order_id, OrderStatus.RECEIVED)
                sqs.send_message(QueueUrl=queue_url, MessageBody=message["Body"],
                                 MessageAttributes=message.get("MessageAttributes", {}))
                sqs.delete_message(QueueUrl=dlq_url, ReceiptHandle=message["ReceiptHandle"])
                moved += 1
                logger.info(json.dumps({"event": "redrive_completed", "run_id": run_id,
                                        "operator": operator, "order_id": order_id}))
                if moved >= max_messages:
                    break
            except (KeyError, ValueError, ClientError) as error:
                logger.exception("Redrive stopped with message retained", extra={"run_id": run_id,
                                                                                "error": str(error)})
                raise
    return moved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-messages", type=int, required=True, help="Required cap (1-100)")
    parser.add_argument("--operator", required=True, help="Operator identity for audit logs")
    args = parser.parse_args()
    print(f"Redriven {redrive(args.max_messages, args.operator)} message(s)")
