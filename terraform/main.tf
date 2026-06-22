module "budget" {
  source = "./modules/budget"

  providers = {
    aws = aws.us_east_1  # Budgets API is global but routed through us-east-1
  }

  budget_name      = "${var.project}-monthly-budget"
  budget_limit_usd = var.budget_limit_usd
  alert_email      = var.alert_email
}

module "config_tagging" {
  source = "./modules/config-tagging"

  project                = var.project
  alert_email            = var.alert_email
  enable_config_recorder = var.enable_config_recorder
  required_tags          = ["CostCenter", "Environment", "Project", "Owner"]
}

module "asg" {
  source = "./modules/asg-mixed-instances"

  project      = var.project
  environment  = var.environment
  vpc_cidr     = var.vpc_cidr
  subnet_cidrs = var.subnet_cidrs

  min_capacity                    = var.min_capacity
  max_capacity                    = var.max_capacity
  desired_capacity                = var.desired_capacity
  on_demand_base_capacity         = var.on_demand_base_capacity
  on_demand_percentage_above_base = var.on_demand_percentage_above_base
  key_pair_name                   = var.key_pair_name
}
