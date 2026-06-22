# AWS Cost Optimisation — End-to-End Practical Guide

**Audience:** Platform Engineers, FinOps Analysts, DevSecOps Teams  
**Scope:** AWS accounts at any scale — from startup to enterprise  
**Updated:** June 2026

---

## Introduction

AWS cost optimisation is not a one-time project — it is a continuous discipline. This guide gives you a repeatable framework that any team can apply regardless of AWS experience level. It follows the **Identify → Govern → Optimise → Monitor** cycle and addresses each phase with concrete, implementable steps.

Every recommendation in this guide has been tested in production environments. Dollar figures are approximate, based on us-east-1 On-Demand pricing as of mid-2026.

---

## Part 1 — Identify: Finding Waste Before It Compounds

### 1.1 AWS Cost Explorer

Cost Explorer is your primary visibility tool. Enable it once and it retroactively loads 12 months of billing data.

**Enable Cost Explorer:**
1. AWS Console → Billing → Cost Explorer → Enable

**Key views to check immediately:**
- **Service breakdown** (last 30 days): Find which service drives the most spend
- **Daily spend graph**: Look for unexpected spikes
- **Group by Tag → CostCenter**: Check if spend is attributable (blank = untagged)

**Hourly granularity** (for EC2 and S3 deep-dives):
```
Cost Explorer → Filter by Service: EC2 → Group by: Usage Type → Granularity: Hourly
```

**Actionable threshold:** Any service consuming >30% of total spend without a clear business justification is a candidate for immediate review.

---

### 1.2 AWS Trusted Advisor

Trusted Advisor has a "Cost Optimization" category that automatically flags:

| Check | What it finds |
|---|---|
| Idle EC2 Instances | Instances with <10% CPU over 14 days |
| Unassociated EIPs | Elastic IPs not attached to a running instance |
| Underutilised EBS | Volumes with very low I/O |
| Idle Load Balancers | ALBs/NLBs with no healthy targets |
| Underutilised RDS | DB instances with <5% CPU |
| S3 Bucket Policies | Buckets with public write access incurring unexpected traffic |

> **Tip:** Business Support or Enterprise Support tiers unlock all Trusted Advisor checks. On the free tier, only a subset of cost checks is available.

**How to access:**
```
AWS Console → Trusted Advisor → Cost Optimization → [Select any check]
```

---

### 1.3 Automated Zombie Asset Detection

The Trusted Advisor console is useful for a quick scan, but it does not give you programmatic access suitable for CI pipelines or scheduled jobs. Use the scripts in this repo:

```bash
# Dry-run: report zombie assets without deleting
python scripts/garbage_collect.py --region us-east-1

# Scan all regions and get a JSON report
python scripts/garbage_collect.py --all-regions --output zombie_report.json

# Actually delete (requires interactive confirmation)
python scripts/garbage_collect.py --region us-east-1 --delete

# Bash version (requires AWS CLI + jq)
bash scripts/garbage_collect.sh --region us-east-1
```

**What constitutes a zombie asset:**

| Asset | Zombie Condition | Monthly Cost |
|---|---|---|
| EBS Volume | `State = available` (no attachment) | $0.08–$0.10/GB |
| Elastic IP | No `AssociationId` | $3.60 |
| Stopped EC2 | Stopped >7 days (EBS continues billing) | Varies |
| Idle RDS | <5% CPU + 0 connections >7 days | Full instance cost |
| Unused NAT GW | No traffic >7 days | $32/month + data |
| Orphan Snapshots | Parent volume deleted | $0.05/GB |

**Typical waste in an inherited account:** $150–$2,000/month from unmanaged assets alone.

---

### 1.4 Finding Orphaned Snapshots

Garbage collect also covers EBS snapshots whose parent volumes have been deleted:

```bash
# List snapshots with no associated volume
aws ec2 describe-snapshots \
  --owner-ids self \
  --query "Snapshots[?!not_null(VolumeId)] | [?StartTime<='$(date -d '90 days ago' +%Y-%m-%d)'].{ID:SnapshotId,Size:VolumeSize,Date:StartTime}" \
  --output table
```

---

## Part 2 — Govern: Preventing Waste at the Source

### 2.1 AWS Budgets

Budgets send alerts **before** you overspend — the best early-warning system available.

**Deploy the budget stack:**
```bash
aws cloudformation deploy \
  --template-file governance/budget_alert.yaml \
  --stack-name cost-detective-budget \
  --parameter-overrides \
    AlertEmail=yourteam@company.com \
    BudgetLimitUSD=50 \
  --capabilities CAPABILITY_NAMED_IAM
```

**Budget types to set up (recommended set):**

| Budget | Amount | Alert at |
|---|---|---|
| Total Account Monthly | $X (your limit) | 80%, 100%, forecasted |
| EC2 Monthly | EC2 sub-budget | 80%, 100% |
| Data Transfer | $50 | 80%, 100% |
| Per-CostCenter | $Y per team | 80%, 100% |

**Budget Actions** (auto-remediate overspend):
- Attach an IAM policy that denies `ec2:RunInstances` when a budget threshold is exceeded
- This gives you a hard stop on runaway provisioning

---

### 2.2 Tagging Policy

Tags are how you hold teams accountable. Without `CostCenter`, you cannot do chargeback. Without `Environment`, you cannot create IAM policies that distinguish prod from dev.

**Mandatory tags (enforced):** `CostCenter`, `Environment`, `Project`, `Owner`

Full policy: see `governance/tagging_policy.md`

**Deploy Config rule:**
```bash
aws cloudformation deploy \
  --template-file governance/config_tagging_rule.yaml \
  --stack-name cost-detective-config \
  --parameter-overrides \
    AlertEmail=yourteam@company.com \
    EnableConfigRecorder=false \   # set true if Config not yet enabled
  --capabilities CAPABILITY_NAMED_IAM
```

**Check compliance immediately:**
```bash
python scripts/tag_compliance_check.py --region us-east-1
```

---

### 2.3 Service Control Policies

SCPs operate at the AWS Organizations level and are the strongest preventive control. They cannot be overridden even by account root.

**The SCP in this repo** (`governance/scp_require_tag.json`) denies:
- `ec2:RunInstances` without `CostCenter` tag
- `ec2:RunInstances` without `Environment` tag
- `ec2:CreateVolume` without `CostCenter` tag
- `ec2:DeleteTags` for mandatory tag keys

**To apply an SCP via AWS CLI:**
```bash
# Create the policy
aws organizations create-policy \
  --name "RequireCostCenterTag" \
  --description "Deny EC2 launch without mandatory tags" \
  --content file://governance/scp_require_tag.json \
  --type SERVICE_CONTROL_POLICY

# Attach to a target OU
aws organizations attach-policy \
  --policy-id p-xxxxxxxxxxxx \
  --target-id ou-xxxx-xxxxxxxx
```

> **Warning:** Always test SCPs in a sandbox OU before applying to production. A misconfigured SCP can lock out all principals including administrators.

---

### 2.4 IAM Permission Boundaries for Developers

Limit what developers can do in sandbox accounts without going through the SCP route:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:RunInstances"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestTag/Environment": ["dev", "sandbox"]
        },
        "StringLike": {
          "ec2:InstanceType": ["t3.*", "t3a.*"]
        }
      }
    }
  ]
}
```

This restricts developers to only launching small instance types in non-production environments.

---

## Part 3 — Optimise: Architecture for Cost Efficiency

### 3.1 Right-Sizing EC2 Instances

Right-sizing is the highest-ROI optimisation for most accounts with legacy infrastructure.

**Step 1: Identify candidates**
```bash
# Use AWS Compute Optimizer (free, AI-driven recommendations)
aws compute-optimizer get-ec2-instance-recommendations \
  --output table \
  --query 'instanceRecommendations[*].{ID:instanceArn,Type:currentInstanceType,Rec:recommendationOptions[0].instanceType,Saving:recommendationOptions[0].estimatedMonthlySavings.value}'
```

**Step 2: Validate with CloudWatch metrics**

Look at `CPUUtilization`, `NetworkIn`, `NetworkOut`, `mem_used_percent` (if CloudWatch Agent is installed) over the last 14–30 days.

**Right-sizing rule of thumb:**

| Average CPU | Action |
|---|---|
| <5% | Downsize 2 generations |
| 5–20% | Downsize 1 generation |
| 20–60% | Correctly sized |
| >80% | Upsize or scale horizontally |

**Typical savings:** 30–60% from right-sizing alone.

---

### 3.2 Spot Instances for Stateless Workloads

Spot Instances offer up to **90% discount** vs On-Demand. They are suitable for:
- Web/application tiers behind a load balancer
- Batch processing (data pipelines, ETL, ML training)
- CI/CD build agents
- Auto Scaling group scale-out capacity

**Key Spot best practices:**

1. **Diversify instance types** — specify 5+ similar types so AWS can find available capacity
2. **Use `price-capacity-optimized` strategy** — reduces interruption probability vs `lowest-price`
3. **Handle interruptions gracefully** — 2-minute warning via EC2 Spot interruption notice
4. **Keep base capacity On-Demand** — provides a reliability floor

**Deploy the ASG:**
```bash
aws cloudformation deploy \
  --template-file infrastructure/asg_mixed_instances.yaml \
  --stack-name cost-detective-asg \
  --parameter-overrides \
    CostCenter=ENG-001 \
    Environment=dev \
    Project=cost-detective \
    MinCapacity=1 \
    MaxCapacity=6 \
    OnDemandBaseCapacity=1 \
    OnDemandPercentageAboveBase=25 \
  --capabilities CAPABILITY_NAMED_IAM
```

**Spot interruption handling in your application:**
```bash
# Check for interruption notice (poll from within instance)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/spot/instance-action
# Returns {"action":"terminate","time":"2026-06-22T14:30:00Z"} if interruption is imminent
```

For containerised workloads, the [AWS Node Termination Handler](https://github.com/aws/aws-node-termination-handler) handles this automatically.

---

### 3.3 Savings Plans and Reserved Instances

For **predictable baseline capacity**, Savings Plans offer 30–66% savings over On-Demand with a 1 or 3-year commitment.

**Which to buy:**

| Type | Flexibility | Discount |
|---|---|---|
| Compute Savings Plan | Any instance family, size, AZ, region, OS | Up to 66% |
| EC2 Instance Savings Plan | Specific family + region, any size/OS | Up to 72% |
| Reserved Instance | Specific type + AZ, OS | Up to 72% |

**When to buy:** After your baseline capacity has been stable for 2+ months. Buying too early risks paying for unused commitments.

**Recommendation:**
1. Run 3–6 months on On-Demand
2. Use Compute Optimizer / Cost Explorer recommendations to identify steady-state
3. Purchase Compute Savings Plans for 70% of steady-state baseline (leaves 30% buffer)
4. Use Spot or On-Demand for the remainder

---

### 3.4 S3 Cost Optimisation

S3 is frequently the hidden cost driver. Key levers:

```bash
# Enable S3 Intelligent-Tiering for large buckets
aws s3api put-bucket-intelligent-tiering-configuration \
  --bucket YOUR_BUCKET \
  --id "CostDetectiveIT" \
  --intelligent-tiering-configuration '{
    "Id": "CostDetectiveIT",
    "Status": "Enabled",
    "Tierings": [
      {"Days": 90, "AccessTier": "ARCHIVE_ACCESS"},
      {"Days": 180, "AccessTier": "DEEP_ARCHIVE_ACCESS"}
    ]
  }'

# Find buckets without lifecycle policies
aws s3api list-buckets --query 'Buckets[*].Name' --output text | \
  tr '\t' '\n' | xargs -I{} sh -c \
  'aws s3api get-bucket-lifecycle-configuration --bucket {} 2>/dev/null || echo "NO LIFECYCLE: {}"'
```

**S3 cost levers:**

| Action | Savings |
|---|---|
| Intelligent-Tiering for cold data | 40–68% |
| Lifecycle to Glacier after 90 days | 80–93% |
| Delete incomplete multipart uploads | Varies |
| S3 Transfer Acceleration — disable if unused | $0.04/GB |
| Request Pays on shared datasets | Full shift to requester |

---

### 3.5 Data Transfer Cost Reduction

Data transfer is often invisible until it dominates the bill.

**Common culprits:**

| Scenario | Cost | Fix |
|---|---|---|
| EC2 → Internet (uncompressed) | $0.09/GB | Enable HTTP compression |
| Cross-AZ traffic | $0.01/GB each direction | Co-locate services in same AZ |
| Cross-region replication | $0.02–$0.08/GB | Justify per use case |
| NAT Gateway data processing | $0.045/GB | Use VPC endpoints for AWS services |

**VPC Endpoints eliminate NAT Gateway charges for AWS API traffic:**
```bash
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxx \
  --service-name com.amazonaws.us-east-1.s3 \
  --route-table-ids rtb-xxxxx \
  --vpc-endpoint-type Gateway
```

---

## Part 4 — Monitor: Staying Ahead of Cost Creep

### 4.1 Cost Anomaly Detection

AWS Cost Anomaly Detection uses ML to flag unusual spending automatically.

```bash
# Create an anomaly monitor for your entire account
aws ce create-anomaly-monitor \
  --anomaly-monitor '{
    "MonitorName": "AccountWideMonitor",
    "MonitorType": "DIMENSIONAL",
    "MonitorDimension": "SERVICE"
  }'

# Create an alert subscription ($10 threshold)
aws ce create-anomaly-subscription \
  --anomaly-subscription '{
    "SubscriptionName": "DailyCostAlert",
    "Threshold": 10,
    "Frequency": "DAILY",
    "MonitorArnList": ["arn:aws:ce::123456789012:anomalymonitor/..."],
    "Subscribers": [
      {"Address": "yourteam@company.com", "Type": "EMAIL"}
    ]
  }'
```

### 4.2 CloudWatch Billing Alarms

For real-time alerting (separate from AWS Budgets):

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "EstimatedChargesAlert" \
  --alarm-description "Alert when charges exceed $40" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 40 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:billing-alerts \
  --dimensions Name=Currency,Value=USD
```

> **Note:** Billing metrics are only available in `us-east-1`. Set `--region us-east-1` for this command.

### 4.3 Weekly FinOps Cadence

Establish a repeating review rhythm:

| Day | Activity | Tool |
|---|---|---|
| Monday | Review prior week spend | Cost Explorer |
| Monday | Check AWS Budgets dashboard | AWS Console |
| Wednesday | Run tag compliance check | `tag_compliance_check.py` |
| Friday | Review Trusted Advisor recommendations | AWS Console |
| Monthly | Chargeback report to team leads | Cost Explorer CUR + Athena |
| Quarterly | Savings Plan / RI review | Cost Explorer — Recommendations |

---

## Part 5 — Quick-Reference Cheat Sheet

### Finding Zombie Resources

```bash
# Unattached EBS volumes
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[*].{ID:VolumeId,Size:Size,Type:VolumeType}' --output table

# Unassociated Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].{IP:PublicIp,ID:AllocationId}' --output table

# Stopped instances >7 days
aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=stopped \
  --query 'Reservations[*].Instances[*].{ID:InstanceId,Type:InstanceType,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table

# Idle load balancers (no targets or no traffic last 7 days)
aws elbv2 describe-load-balancers --query 'LoadBalancers[*].LoadBalancerArn' --output text | \
  tr '\t' '\n' | xargs -I{} aws elbv2 describe-target-groups --load-balancer-arn {} \
  --query 'TargetGroups[?TargetType!=`lambda`].TargetGroupArn' --output text
```

### Cost Explorer via CLI

```bash
# Last 30 days by service
aws ce get-cost-and-usage \
  --time-period Start=$(date -d '30 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[*].{Service:Keys[0],Cost:Metrics.UnblendedCost.Amount}' \
  --output table | sort -k3 -rn

# Forecast for rest of month
aws ce get-cost-forecast \
  --time-period Start=$(date +%Y-%m-%d),End=$(date -d 'next month' +%Y-%m-01) \
  --metric UNBLENDED_COST \
  --granularity MONTHLY
```

### Spot Savings Estimate

For any On-Demand instance, check current Spot pricing:
```bash
aws ec2 describe-spot-price-history \
  --instance-types t3.medium \
  --product-descriptions "Linux/UNIX" \
  --max-items 5 \
  --query 'SpotPriceHistory[*].{AZ:AvailabilityZone,Price:SpotPrice,Time:Timestamp}' \
  --output table
```

---

## Summary: Priority Action List

For an inherited, unoptimised AWS account, tackle in this order:

1. **Enable Cost Explorer** — gain visibility (free, takes 24h to populate)
2. **Set a Budget alert at $50** — early warning system
3. **Run garbage_collect.py** — kill obvious waste today
4. **Deploy Config required-tags rule** — start catching ungoverned resources
5. **Apply SCP to sandbox OU** — prevent new ungoverned resources
6. **Right-size EC2** — biggest bang for buck after cleanup
7. **Migrate stateless workloads to Spot** — up to 70% savings
8. **Enable S3 Intelligent-Tiering** — passive, zero-effort storage savings
9. **Create VPC Endpoints** — eliminate NAT Gateway data charges for AWS API calls
10. **Purchase Savings Plans** — lock in baseline savings after 3–6 months of stable usage
