# Dead Letter Queue
resource "aws_sqs_queue" "orders_dlq" {
  name                      = "${var.app_name}-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days retention for inspection
}

# Main SQS Standard Queue
resource "aws_sqs_queue" "orders_queue" {
  name                       = "${var.app_name}-queue-${var.environment}"
  visibility_timeout_seconds = 60 # Worker Lambda timeout (15s) * 4 for safe retry processing
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 10     # Long polling enabled to minimize empty reads

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 3
  })
}

# DLQ Redrive Allow Policy
resource "aws_sqs_queue_redrive_allow_policy" "dlq_redrive_allow" {
  queue_url = aws_sqs_queue.orders_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.orders_queue.arn]
  })
}
