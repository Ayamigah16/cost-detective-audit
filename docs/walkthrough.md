# Cost Detective — Live Walkthrough Script

**Duration:** ~30 minutes  
**Format:** Screen share + terminal demo  
**Prerequisites:** AWS CLI configured, Python 3.10+, boto3 installed

---

## Before You Begin

```bash
# Verify AWS CLI is configured
aws sts get-caller-identity

# Install Python dependencies
pip install boto3

# Set your region
export AWS_DEFAULT_REGION=us-east-1
```

---

## Act 1 — Create the Crime Scene (5 min)

> "We've just inherited this account. Let me show you what the previous team left behind."

```bash
# Create zombie resources (EBS volumes + Elastic IPs + idle EC2)
python scripts/setup_sandbox.py --region us-east-1 --no-ec2

# Confirm resources exist in AWS console or via CLI
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[*].{ID:VolumeId,Size:Size,Type:VolumeType}' \
  --output table

aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].{IP:PublicIp,ID:AllocationId}' \
  --output table
```

**Show:** AWS Console → EC2 → Volumes → filter by "available"  
**Show:** AWS Console → EC2 → Elastic IPs → highlight unassociated entries

---

## Act 2 — Detect the Waste (10 min)

### 2a. Trusted Advisor

> "First place to check is Trusted Advisor — it gives us a quick automated scan."

1. Open AWS Console → Trusted Advisor → Cost Optimization
2. Walk through: **Low Utilization EC2**, **Unassociated EIPs**, **Underutilized EBS**
3. Take a screenshot for the report

### 2b. Cost Explorer

> "Now let's look at where the money is actually going."

1. AWS Console → Billing → Cost Explorer → Enable (if not already)
2. Set date range: last 30 days
3. Group by: Service
4. Highlight top spender(s)
5. Change group by to Tag → CostCenter → show blank/untagged spend

### 2c. Garbage Collector — Python

```bash
# Dry-run: report findings without deleting anything
python scripts/garbage_collect.py --region us-east-1

# Note the output: zombie volumes, unused EIPs, cost estimates
```

### 2d. Garbage Collector — Bash

```bash
# Same logic, pure bash/AWS CLI
bash scripts/garbage_collect.sh --region us-east-1
```

### 2e. Tag Compliance

```bash
# Check tagging compliance across all resources
python scripts/tag_compliance_check.py --region us-east-1

# Show: 0% compliance — CostCenter missing everywhere
```

---

## Act 3 — Clean Up (3 min)

> "Now that we know exactly what to kill, let's run the actual cleanup."

```bash
# Python version — interactive confirmation required
python scripts/garbage_collect.py --region us-east-1 --delete
# Type: DELETE

# OR using Bash
bash scripts/garbage_collect.sh --region us-east-1 --delete
```

**Verify cleanup:**
```bash
# Should return empty list
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[*].VolumeId' \
  --output text

aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].PublicIp' \
  --output text
```

---

## Act 4 — Deploy Governance Controls (7 min)

### 4a. AWS Budget + SNS Alerts

```bash
aws cloudformation deploy \
  --template-file governance/budget_alert.yaml \
  --stack-name cost-detective-budget \
  --parameter-overrides \
    AlertEmail=yourteam@company.com \
    BudgetLimitUSD=50 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

**Show:** AWS Console → Billing → Budgets → confirm budget exists with 3 alert thresholds

### 4b. AWS Config Required-Tags Rule

```bash
aws cloudformation deploy \
  --template-file governance/config_tagging_rule.yaml \
  --stack-name cost-detective-config \
  --parameter-overrides \
    AlertEmail=yourteam@company.com \
    EnableConfigRecorder=false \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

**Show:** AWS Console → AWS Config → Rules → `cost-detective-required-tags`  
**Highlight:** Compliance status of existing resources

### 4c. SCP Discussion

> "The SCP is our strongest control — it operates at the Organizations level and cannot be bypassed even by account root."

```bash
# Review the SCP (don't apply live during demo — use sandbox OU in practice)
cat governance/scp_require_tag.json | python -m json.tool
```

**Walk through the key statements:**
- `DenyEC2RunInstancesWithoutCostCenterTag` — preventive block at launch
- `DenyTagRemovalFromTaggedResources` — prevents removing mandatory tags after the fact
- Exemptions list — CloudFormation, BreakGlass, service-linked roles

---

## Act 5 — Cost-Optimised Architecture (5 min)

### 5a. Deploy ASG with Mixed Instances

```bash
aws cloudformation deploy \
  --template-file infrastructure/asg_mixed_instances.yaml \
  --stack-name cost-detective-asg \
  --parameter-overrides \
    CostCenter=ENG-001 \
    Environment=dev \
    Project=cost-detective \
    MinCapacity=1 \
    MaxCapacity=4 \
    OnDemandBaseCapacity=1 \
    OnDemandPercentageAboveBase=25 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

**Show:** AWS Console → EC2 → Auto Scaling Groups → `cost-detective-asg`
- Click "Instance Management" tab → see lifecycle column (spot vs normal)
- Click "Instance Refresh" → explain rolling updates

### 5b. Verify Spot Instances

```bash
# Check which instances are Spot vs On-Demand
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=cost-detective" \
  --query 'Reservations[*].Instances[*].{ID:InstanceId,Type:InstanceType,Lifecycle:InstanceLifecycle,State:State.Name}' \
  --output table
```

**Explain:** `Lifecycle = spot` = running at 60–90% discount. `Lifecycle = null/normal` = On-Demand base.

### 5c. Spot Pricing Check

```bash
# Show real-time Spot vs On-Demand prices
aws ec2 describe-spot-price-history \
  --instance-types t3.micro t3.small t3.medium \
  --product-descriptions "Linux/UNIX" \
  --max-items 6 \
  --query 'SpotPriceHistory[*].{AZ:AvailabilityZone,Type:InstanceType,Spot:SpotPrice}' \
  --output table
```

---

## Act 6 — Summary & Next Steps (2 min)

> "Here's what we've accomplished in this session:"

1. **Identified** $91/month in zombie assets using Trusted Advisor + custom scripts
2. **Deleted** all zombie assets — zero cost, zero blast radius
3. **Deployed** a Budget alert so we're never surprised by an overspend again
4. **Deployed** a Config rule that continuously monitors tag compliance
5. **Drafted** an SCP that prevents new ungoverned resources from being created
6. **Deployed** a Spot-first ASG that saves ~40% vs all-On-Demand
7. **Published** a tagging policy and end-to-end optimisation guide

**Total monthly savings identified: ~$141/month = ~$1,689/year**

---

## Cleanup After Walkthrough

```bash
# Remove all sandbox resources
python scripts/setup_sandbox.py --cleanup

# Delete CloudFormation stacks (in order)
aws cloudformation delete-stack --stack-name cost-detective-asg --region us-east-1
aws cloudformation delete-stack --stack-name cost-detective-config --region us-east-1
aws cloudformation delete-stack --stack-name cost-detective-budget --region us-east-1
```

---

## Q&A Crib Sheet

**Q: What if I can't use SCPs (single account, no Organizations)?**  
A: Use IAM permission boundaries on developer roles + AWS Config rules for detective controls.

**Q: Can I run the garbage collector in CI/CD?**  
A: Yes. Use `--force` flag to skip confirmation. Recommended pattern: dry-run on PR merge, actual delete on a scheduled job with approval gate.

**Q: How do I handle existing untagged resources from before this policy?**  
A: Use `tag_compliance_check.py --fix-dryrun` to generate remediation commands. Batch-apply with a wrapper script. Legacy resources are Config-flagged but SCP-exempt (they already exist).

**Q: Will the Spot interruption break our application?**  
A: With proper ASG health checks, the ALB drains connections gracefully and the ASG replaces the instance automatically. For zero-downtime: `MinInstancesInService: 1` in the update policy ensures at least one healthy instance at all times.

**Q: How often should we run the garbage collector?**  
A: Weekly on all regions as a scheduled Lambda or cron job. Alert on any finding > $10/month. Run manually after any infrastructure teardown event.
