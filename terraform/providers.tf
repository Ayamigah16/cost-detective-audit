provider "aws" {
  region = var.region

  # default_tags propagates these to every resource this provider manages —
  # no need to repeat tags inside individual resources or modules.
  default_tags {
    tags = {
      CostCenter  = var.cost_center
      Environment = var.environment
      Project     = var.project
      Owner       = var.owner
      ManagedBy   = "Terraform"
    }
  }
}

# Separate provider for us-east-1 — CloudWatch Billing metrics and
# Cost Explorer are only available in that region.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      CostCenter  = var.cost_center
      Environment = var.environment
      Project     = var.project
      Owner       = var.owner
      ManagedBy   = "Terraform"
    }
  }
}
