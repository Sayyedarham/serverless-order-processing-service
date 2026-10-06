"""Shared pytest fixtures, moto mocks, and environment setup."""

import os
from collections.abc import Generator
from typing import Any

import boto3
import pytest
from moto import mock_aws

# Configure test environment variables BEFORE importing application code
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["POWERTOOLS_SERVICE_NAME"] = "test-order-service"
os.environ["POWERTOOLS_METRICS_NAMESPACE"] = "TestOrderService"
os.environ["ORDERS_TABLE_NAME"] = "test-serverless-orders"
os.environ["ORDERS_QUEUE_URL"] = (
    "https://sqs.us-east-1.amazonaws.com/123456789012/test-orders-queue"
)
os.environ["ORDERS_DLQ_URL"] = "https://sqs.us-east-1.amazonaws.com/123456789012/test-orders-dlq"
os.environ["API_SHARED_KEY"] = "test-secret-key"
os.environ["DOWNSTREAM_FAILURE_RATE"] = "0.0"
os.environ["ORDER_TTL_DAYS"] = "7"


class DummyLambdaContext:
    def __init__(self, function_name: str = "test-function") -> None:
        self.function_name = function_name
        self.memory_limit_in_mb = 128
        self.invoked_function_arn = (
            f"arn:aws:lambda:us-east-1:123456789012:function:{function_name}"
        )
        self.aws_request_id = "test-request-id-12345"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


@pytest.fixture
def lambda_context() -> DummyLambdaContext:
    return DummyLambdaContext()


@pytest.fixture(autouse=True)
def aws_credentials() -> None:
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture
def mocked_aws() -> Generator[None, None, None]:
    """Provide a clean mock_aws context."""
    with mock_aws():
        yield


@pytest.fixture
def setup_dynamodb(mocked_aws: Any) -> Any:
    """Create mock DynamoDB table matching production schema."""
    import common.dynamo

    common.dynamo._dynamo_resource = None

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.create_table(
        TableName="test-serverless-orders",
        KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "orderId", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "StatusCreatedAtIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def setup_sqs(mocked_aws: Any) -> dict[str, str]:
    """Create mock SQS standard queue and DLQ with redrive policy."""
    import common.sqs

    common.sqs._sqs_client = None

    sqs = boto3.client("sqs", region_name="us-east-1")

    # 1. Create DLQ
    dlq_res = sqs.create_queue(QueueName="test-orders-dlq")
    dlq_url = dlq_res["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]

    # 2. Create Main Queue with redrive policy
    import json

    redrive_policy = {
        "deadLetterTargetArn": dlq_arn,
        "maxReceiveCount": "3",
    }
    main_res = sqs.create_queue(
        QueueName="test-orders-queue",
        Attributes={
            "VisibilityTimeout": "30",
            "RedrivePolicy": json.dumps(redrive_policy),
        },
    )
    queue_url = main_res["QueueUrl"]

    os.environ["ORDERS_QUEUE_URL"] = queue_url
    os.environ["ORDERS_DLQ_URL"] = dlq_url

    # Update common config
    import common.config

    common.config.QUEUE_URL = queue_url
    common.config.DLQ_URL = dlq_url

    return {"queue_url": queue_url, "dlq_url": dlq_url, "dlq_arn": dlq_arn}
