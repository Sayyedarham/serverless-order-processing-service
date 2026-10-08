import os

from aws_lambda_powertools import Logger, Metrics, Tracer

SERVICE_NAME = os.getenv("POWERTOOLS_SERVICE_NAME", "order-processing-service")
NAMESPACE = os.getenv("POWERTOOLS_METRICS_NAMESPACE", "OrderProcessingService")

logger = Logger(service=SERVICE_NAME)
tracer = Tracer(service=SERVICE_NAME)
metrics = Metrics(service=SERVICE_NAME, namespace=NAMESPACE)

TABLE_NAME = os.getenv("ORDERS_TABLE_NAME", "serverless-orders")
QUEUE_URL = os.getenv("ORDERS_QUEUE_URL", "")
DLQ_URL = os.getenv("ORDERS_DLQ_URL", "")
VERIFICATION_QUEUE_URL = os.getenv("VERIFICATION_QUEUE_URL", "")
API_BASE_URL = os.getenv("API_BASE_URL", "")
SERVICE_KEY = os.getenv("API_SHARED_KEY", "")
TTL_DAYS = int(os.getenv("ORDER_TTL_DAYS", "7"))
MAX_RECEIVE_COUNT = int(os.getenv("MAX_RECEIVE_COUNT", "3"))
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
