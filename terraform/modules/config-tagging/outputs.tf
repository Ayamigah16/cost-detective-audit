output "config_rule_name" {
  description = "Name of the AWS Config required-tags rule"
  value       = aws_config_config_rule.required_tags.name
}

output "config_rule_arn" {
  description = "ARN of the AWS Config required-tags rule"
  value       = aws_config_config_rule.required_tags.arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic for Config non-compliance alerts"
  value       = aws_sns_topic.compliance_alerts.arn
}
