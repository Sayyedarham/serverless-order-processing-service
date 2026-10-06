# SNS Alert Topic & Email Subscription
resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts-${var.environment}"
}

resource "aws_sns_topic_subscription" "email_alert" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- CloudWatch Alarms ---

# 1. DLQ Visible Messages Alarm (Immediate alert when messages land in DLQ)
resource "aws_cloudwatch_metric_alarm" "dlq_messages_visible" {
  alarm_name          = "${var.app_name}-dlq-messages-visible-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Alarm triggered when one or more failed orders land in the Dead Letter Queue"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.orders_dlq.name
  }
}

# 2. Ingest Lambda Errors Alarm
resource "aws_cloudwatch_metric_alarm" "ingest_lambda_errors" {
  alarm_name          = "${var.app_name}-ingest-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Alarm triggered when Ingest Lambda experiences runtime errors"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
}

# 3. Worker Lambda Errors Alarm
resource "aws_cloudwatch_metric_alarm" "worker_lambda_errors" {
  alarm_name          = "${var.app_name}-worker-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "Alarm triggered when Worker Lambda errors exceed threshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.worker.function_name
  }
}

# 4. API Gateway 5xx Errors Alarm
resource "aws_cloudwatch_metric_alarm" "api_5xx_errors" {
  alarm_name          = "${var.app_name}-api-5xx-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Alarm triggered when API Gateway returns 5xx server errors"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiId = aws_apigatewayv2_api.http_api.id
    Stage = aws_apigatewayv2_stage.default_stage.name
  }
}

# 5. Worker p99 Latency Alarm
resource "aws_cloudwatch_metric_alarm" "worker_p99_latency" {
  alarm_name          = "${var.app_name}-worker-p99-latency-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 5000 # 5000ms p99 latency threshold
  alarm_description   = "Alarm triggered when Worker Lambda p99 execution duration exceeds 5000ms"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.worker.function_name
  }
}

# --- CloudWatch Dashboard ---

resource "aws_cloudwatch_dashboard" "order_service_dashboard" {
  dashboard_name = "${var.app_name}-overview-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.orders_queue.name, { color = "#1f77b4", label = "Main Queue Visible" }],
            [".", "ApproximateNumberOfMessagesNotVisible", ".", ".", { color = "#aec7e8", label = "Main Queue In-Flight" }],
            [".", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.orders_dlq.name, { color = "#d62728", label = "DLQ Messages (Failures)" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "SQS Queue & DLQ Depth"
          period  = 60
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["OrderProcessingService", "OrdersReceived", { color = "#2ca02c", label = "Orders Received" }],
            [".", "OrdersCompleted", { color = "#1f77b4", label = "Orders Completed" }],
            [".", "OrdersFailed", { color = "#d62728", label = "Orders Failed" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Custom Business Metrics (Orders Lifecycle)"
          period  = 60
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ingest.function_name, { label = "Ingest Invocations" }],
            [".", "Errors", ".", ".", { color = "#d62728", label = "Ingest Errors" }],
            [".", "Invocations", "FunctionName", aws_lambda_function.worker.function_name, { label = "Worker Invocations" }],
            [".", "Errors", ".", ".", { color = "#ff7f0e", label = "Worker Errors" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Lambda Invocations & Errors"
          period  = 60
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.worker.function_name, { stat = "p50", label = "Worker p50 Duration (ms)" }],
            [".", ".", ".", ".", { stat = "p95", label = "Worker p95 Duration (ms)" }],
            [".", ".", ".", ".", { stat = "p99", label = "Worker p99 Duration (ms)" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Worker Lambda Latency Percentiles"
          period  = 60
        }
      }
    ]
  })
}
