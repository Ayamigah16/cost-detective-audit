output "budget_name" {
  description = "Name of the created AWS Budget"
  value       = aws_budgets_budget.monthly.name
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic used for budget alerts"
  value       = aws_sns_topic.budget_alerts.arn
}
