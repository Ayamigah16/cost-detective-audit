data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── (Optional) Config Recorder ─────────────────────────────────────────────
# Only deployed when enable_config_recorder = true and Config isn't already running.

resource "aws_iam_role" "config_recorder" {
  count = var.enable_config_recorder ? 1 : 0

  name = "${var.project}-config-recorder-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  managed_policy_arns = ["arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"]
}

resource "aws_s3_bucket" "config_delivery" {
  count  = var.enable_config_recorder ? 1 : 0
  bucket = "config-delivery-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
}

resource "aws_s3_bucket_versioning" "config_delivery" {
  count  = var.enable_config_recorder ? 1 : 0
  bucket = aws_s3_bucket.config_delivery[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config_delivery" {
  count  = var.enable_config_recorder ? 1 : 0
  bucket = aws_s3_bucket.config_delivery[0].id

  rule {
    id     = "expire-old-snapshots"
    status = "Enabled"
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_policy" "config_delivery" {
  count  = var.enable_config_recorder ? 1 : 0
  bucket = aws_s3_bucket.config_delivery[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSConfigBucketPermissionsCheck"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.config_delivery[0].arn
      },
      {
        Sid       = "AWSConfigBucketDelivery"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.config_delivery[0].arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      }
    ]
  })
}

resource "aws_config_configuration_recorder" "main" {
  count    = var.enable_config_recorder ? 1 : 0
  name     = "default"
  role_arn = aws_iam_role.config_recorder[0].arn

  recording_group {
    all_supported                 = false
    include_global_resource_types = false
    resource_types = [
      "AWS::EC2::Instance",
      "AWS::EC2::Volume",
      "AWS::EC2::NetworkInterface",
      "AWS::EC2::EIP",
    ]
  }
}

resource "aws_config_delivery_channel" "main" {
  count          = var.enable_config_recorder ? 1 : 0
  name           = "default"
  s3_bucket_name = aws_s3_bucket.config_delivery[0].bucket

  snapshot_delivery_properties {
    delivery_frequency = "TwentyFour_Hours"
  }

  depends_on = [aws_config_configuration_recorder.main]
}

resource "aws_config_configuration_recorder_status" "main" {
  count      = var.enable_config_recorder ? 1 : 0
  name       = aws_config_configuration_recorder.main[0].name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.main]
}

# ── Required-Tags Config Rule ──────────────────────────────────────────────
# Maps up to 6 tag keys using tag1Key–tag6Key input parameters.
# Unused slots are omitted via the compact/dynamic pattern below.

locals {
  # Build a map of tagNKey = "KeyName" for however many tags are supplied (max 6)
  tag_params = {
    for idx, key in slice(var.required_tags, 0, min(length(var.required_tags), 6)) :
    "tag${idx + 1}Key" => key
  }
}

resource "aws_config_config_rule" "required_tags" {
  name        = "${var.project}-required-tags"
  description = "Checks that EC2 instances and EBS volumes have all mandatory cost allocation tags."

  source {
    owner             = "AWS"
    source_identifier = "REQUIRED_TAGS"
  }

  scope {
    compliance_resource_types = [
      "AWS::EC2::Instance",
      "AWS::EC2::Volume",
    ]
  }

  input_parameters = jsonencode(local.tag_params)

  depends_on = [aws_config_configuration_recorder_status.main]
}

# ── SNS for non-compliance alerts ──────────────────────────────────────────

resource "aws_sns_topic" "compliance_alerts" {
  name         = "${var.project}-config-compliance-alerts"
  display_name = "Config Compliance Alert"
}

resource "aws_sns_topic_subscription" "compliance_email" {
  topic_arn = aws_sns_topic.compliance_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_policy" "allow_eventbridge" {
  arn = aws_sns_topic.compliance_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowEventBridge"
      Effect = "Allow"
      Principal = {
        Service = "events.amazonaws.com"
      }
      Action   = "sns:Publish"
      Resource = aws_sns_topic.compliance_alerts.arn
    }]
  })
}

# ── EventBridge: fire on Config NON_COMPLIANT ──────────────────────────────

resource "aws_cloudwatch_event_rule" "non_compliant" {
  name        = "${var.project}-config-non-compliance"
  description = "Fires when a resource becomes NON_COMPLIANT with the required-tags rule"

  event_pattern = jsonencode({
    source        = ["aws.config"]
    "detail-type" = ["Config Rules Compliance Change"]
    detail = {
      configRuleName = ["${var.project}-required-tags"]
      newEvaluationResult = {
        complianceType = ["NON_COMPLIANT"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "sns" {
  rule      = aws_cloudwatch_event_rule.non_compliant.name
  target_id = "SendToSNS"
  arn       = aws_sns_topic.compliance_alerts.arn
}
