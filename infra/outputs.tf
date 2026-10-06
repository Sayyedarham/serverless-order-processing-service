output "api_endpoint" {
  description = "Base URL of the deployed HTTP API Gateway"
  value       = aws_apigatewayv2_stage.default_stage.invoke_url
}

output "orders_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.orders.name
}

output "orders_queue_url" {
  description = "SQS standard order queue URL"
  value       = aws_sqs_queue.orders_queue.id
}

output "orders_dlq_url" {
  description = "SQS Dead Letter Queue URL"
  value       = aws_sqs_queue.orders_dlq.id
}

output "sns_topic_arn" {
  description = "SNS alert topic ARN"
  value       = aws_sns_topic.alerts.arn
}

output "github_oidc_role_arn" {
  description = "IAM Role ARN for GitHub Actions OIDC deployment"
  value       = aws_iam_role.github_actions_role.arn
}

output "dashboard_url" {
  description = "Direct AWS Console URL to CloudWatch Operational Dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.order_service_dashboard.dashboard_name}"
}
