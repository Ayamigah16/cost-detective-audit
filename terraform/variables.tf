# ── Shared / provider-level ────────────────────────────────────────────────

variable "region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region to deploy into"
}

# ── Cost allocation tags (applied via default_tags on the provider) ─────────

variable "cost_center" {
  type        = string
  default     = "ENG-001"
  description = "CostCenter tag value for all resources"

  validation {
    condition     = can(regex("^[A-Z]{2,8}-[0-9]{3}$", var.cost_center))
    error_message = "CostCenter must follow the pattern TEAM-NNN (e.g. ENG-001)."
  }
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment tier — used as the Environment tag"

  validation {
    condition     = contains(["prod", "staging", "dev", "sandbox"], var.environment)
    error_message = "environment must be one of: prod, staging, dev, sandbox."
  }
}

variable "project" {
  type        = string
  default     = "cost-detective"
  description = "Project name — used as the Project tag and resource name prefix"
}

variable "owner" {
  type        = string
  default     = "platform@company.com"
  description = "Owner email — used as the Owner tag"
}

# ── Budget module ──────────────────────────────────────────────────────────

variable "alert_email" {
  type        = string
  description = "Email address for budget and compliance alert notifications"

  validation {
    condition     = can(regex("^[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "budget_limit_usd" {
  type        = number
  default     = 50
  description = "Monthly budget threshold in USD"

  validation {
    condition     = var.budget_limit_usd > 0
    error_message = "budget_limit_usd must be a positive number."
  }
}

# ── Config tagging module ──────────────────────────────────────────────────

variable "enable_config_recorder" {
  type        = bool
  default     = false
  description = "Set true only if AWS Config is NOT already enabled in this account/region"
}

# ── ASG module ─────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_cidrs" {
  type    = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "min_capacity" {
  type    = number
  default = 1
}

variable "max_capacity" {
  type    = number
  default = 6
}

variable "desired_capacity" {
  type    = number
  default = 2
}

variable "on_demand_base_capacity" {
  type        = number
  default     = 1
  description = "On-Demand instances to keep as a reliability floor (never replaced by Spot)"
}

variable "on_demand_percentage_above_base" {
  type        = number
  default     = 25
  description = "Percentage of scale-out instances to run as On-Demand; remainder are Spot"

  validation {
    condition     = var.on_demand_percentage_above_base >= 0 && var.on_demand_percentage_above_base <= 100
    error_message = "on_demand_percentage_above_base must be between 0 and 100."
  }
}

variable "key_pair_name" {
  type        = string
  default     = ""
  description = "EC2 Key Pair name for SSH access. Leave empty to use SSM Session Manager only."
}
