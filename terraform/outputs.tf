output "budget_name" {
  description = "Name of the AWS Budget"
  value       = module.budget.budget_name
}

output "budget_sns_topic_arn" {
  description = "ARN of the SNS topic receiving budget alerts"
  value       = module.budget.sns_topic_arn
}

output "config_rule_name" {
  description = "Name of the AWS Config required-tags rule"
  value       = module.config_tagging.config_rule_name
}

output "config_compliance_sns_arn" {
  description = "ARN of the SNS topic for Config non-compliance alerts"
  value       = module.config_tagging.sns_topic_arn
}

output "asg_name" {
  description = "Auto Scaling Group name"
  value       = module.asg.asg_name
}

output "launch_template_id" {
  description = "Launch Template ID"
  value       = module.asg.launch_template_id
}

output "vpc_id" {
  description = "VPC ID created for the ASG workload"
  value       = module.asg.vpc_id
}

output "estimated_spot_savings_note" {
  description = "Rough savings estimate vs all-On-Demand"
  value       = "With ${var.on_demand_base_capacity} On-Demand base and ${var.on_demand_percentage_above_base}% On-Demand above base, ~${100 - var.on_demand_percentage_above_base}% of scale-out runs as Spot — typically 60-70% cheaper than On-Demand."
}
