variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "prod"
}

variable "app_name" {
  description = "Application base name"
  type        = string
  default     = "serverless-orders"
}

variable "alert_email" {
  description = "Email address for $1 budget alert and DLQ CloudWatch alarm notifications"
  type        = string
  default     = "sayyedarhamali@gmail.com"
}

variable "api_shared_key" {
  description = "Optional shared secret key for write endpoints (leave empty for public portfolio demo)"
  type        = string
  default     = ""
}

variable "downstream_failure_rate" {
  description = "Downstream service injected failure rate (0.0 to 1.0) for testing"
  type        = string
  default     = "0.0"
}

variable "github_repo" {
  description = "GitHub repository name (owner/repo) for OIDC trust"
  type        = string
  default     = "Sayyedarham/serverless-order-processing-service"
}
