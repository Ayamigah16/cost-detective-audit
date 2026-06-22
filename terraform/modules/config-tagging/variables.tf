variable "project" {
  type        = string
  description = "Project name prefix for resource naming"
}

variable "alert_email" {
  type        = string
  description = "Email for Config non-compliance notifications"
}

variable "required_tags" {
  type        = list(string)
  description = "Tag keys that must be present on EC2 instances and EBS volumes"
  default     = ["CostCenter", "Environment", "Project", "Owner"]

  validation {
    condition     = length(var.required_tags) <= 6
    error_message = "The AWS required-tags Config rule supports a maximum of 6 tag keys."
  }
}

variable "enable_config_recorder" {
  type        = bool
  default     = false
  description = "Create a Config recorder. Set false if Config is already enabled in this account/region."
}
