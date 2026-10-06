resource "aws_budgets_budget" "zero_cost_budget" {
  name              = "${var.app_name}-safety-budget-${var.environment}"
  budget_type       = "COST"
  limit_amount      = "1.0"
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-10-01_00:00"

  cost_types {
    include_tax          = true
    include_subscription = true
    use_blended          = false
    include_refund       = false
    include_credit       = false
    include_upfront      = true
    include_recurring    = true
    include_support      = true
    include_discount     = true
    use_amortized        = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
