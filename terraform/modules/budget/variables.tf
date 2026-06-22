variable "budget_name" {
  type        = string
  description = "Name of the AWS Budget"
}

variable "budget_limit_usd" {
  type        = number
  description = "Monthly budget limit in USD"
}

variable "alert_email" {
  type        = string
  description = "Email address for SNS subscription and direct budget notifications"
}
