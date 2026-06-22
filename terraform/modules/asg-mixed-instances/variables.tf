variable "project" {
  type        = string
  description = "Project name — used as a prefix for all resource names"
}

variable "environment" {
  type        = string
  description = "Deployment tier (prod | staging | dev | sandbox)"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_cidrs" {
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
  description = "CIDR blocks for public subnets — one per AZ"
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
  description = "Number of On-Demand instances to maintain as a reliability floor"
}

variable "on_demand_percentage_above_base" {
  type        = number
  default     = 25
  description = "Percentage of scale-out capacity to run as On-Demand; the rest becomes Spot"
}

variable "key_pair_name" {
  type        = string
  default     = ""
  description = "EC2 Key Pair name. Leave empty to use SSM Session Manager only."
}

# Instance types offered as Spot overrides — diversify to reduce interruption risk.
variable "spot_instance_types" {
  type = list(string)
  default = [
    "t3.micro",
    "t3a.micro",
    "t2.micro",
    "t3.small",
    "t3a.small",
    "t3.medium",
    "t3a.medium",
  ]
  description = "Instance types offered across the mixed Spot/On-Demand pool"
}
