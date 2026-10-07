# --- Packaging Lambda Layer & Source Code ---

data "archive_file" "layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../build/layer"
  output_path = "${path.module}/../build/dist/powertools_layer.zip"
}

resource "aws_lambda_layer_version" "powertools_layer" {
  filename            = data.archive_file.layer_zip.output_path
  source_code_hash    = data.archive_file.layer_zip.output_base64sha256
  layer_name          = "${var.app_name}-dependencies-${var.environment}"
  compatible_runtimes = ["python3.12"]
  description         = "AWS Lambda Powertools and Pydantic v2 runtime layer"
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/../build/dist/lambda.zip"
}

# --- CloudWatch Log Groups with 7-Day Retention ---

resource "aws_cloudwatch_log_group" "ingest_logs" {
  name              = "/aws/lambda/${var.app_name}-ingest-${var.environment}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "worker_logs" {
  name              = "/aws/lambda/${var.app_name}-worker-${var.environment}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "status_logs" {
  name              = "/aws/lambda/${var.app_name}-status-${var.environment}"
  retention_in_days = 7
}

# --- Ingest Lambda Function ---

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.app_name}-ingest-${var.environment}"
  description      = "Validates order payload, writes to DynamoDB conditionally, and queues to SQS"
  role             = aws_iam_role.lambda_role.arn
  handler          = "ingest.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [aws_lambda_layer_version.powertools_layer.arn]

  environment {
    variables = {
      ORDERS_TABLE_NAME            = aws_dynamodb_table.orders.name
      ORDERS_QUEUE_URL             = aws_sqs_queue.orders_queue.id
      API_SHARED_KEY               = var.api_shared_key
      POWERTOOLS_SERVICE_NAME      = "order-ingest"
      POWERTOOLS_METRICS_NAMESPACE = "OrderProcessingService"
      ORDER_TTL_DAYS               = "7"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.ingest_logs,
    aws_iam_role_policy.lambda_policy
  ]
}

# --- Worker Lambda Function ---

resource "aws_lambda_function" "worker" {
  function_name    = "${var.app_name}-worker-${var.environment}"
  description      = "Processes SQS batches with partial batch failures and simulated downstream flakiness"
  role             = aws_iam_role.lambda_role.arn
  handler          = "worker.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 15
  memory_size      = 256
  layers           = [aws_lambda_layer_version.powertools_layer.arn]

  environment {
    variables = {
      ORDERS_TABLE_NAME            = aws_dynamodb_table.orders.name
      ORDERS_QUEUE_URL             = aws_sqs_queue.orders_queue.id
      POWERTOOLS_SERVICE_NAME      = "order-worker"
      POWERTOOLS_METRICS_NAMESPACE = "OrderProcessingService"
      MAX_RECEIVE_COUNT           = "3"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.worker_logs,
    aws_iam_role_policy.lambda_policy
  ]
}

# SQS Event Source Mapping with Partial Batch Item Failures
resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn                   = aws_sqs_queue.orders_queue.arn
  function_name                      = aws_lambda_function.worker.arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]
}

# --- Status Lambda Function ---

resource "aws_lambda_function" "status" {
  function_name    = "${var.app_name}-status-${var.environment}"
  description      = "Retrieves order status from DynamoDB and provides health check"
  role             = aws_iam_role.lambda_role.arn
  handler          = "status.handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 10
  memory_size      = 256
  layers           = [aws_lambda_layer_version.powertools_layer.arn]

  environment {
    variables = {
      ORDERS_TABLE_NAME            = aws_dynamodb_table.orders.name
      POWERTOOLS_SERVICE_NAME      = "order-status"
      POWERTOOLS_METRICS_NAMESPACE = "OrderProcessingService"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.status_logs,
    aws_iam_role_policy.lambda_policy
  ]
}
