# Cost Detective — AWS FinOps Audit

A complete AWS cost governance and optimisation toolkit for inherited or ungoverned AWS accounts.

**Scenario:** Your organisation has inherited an AWS account from a previous team that was reckless with spending. Your budget is tight. This project identifies waste, implements governance, and architects cost-efficient solutions.

---

## Project Structure

```
cost-detective-audit/
├── AUDIT_REPORT.md                      Full audit findings and financial impact
├── scripts/
│   ├── setup_sandbox.py                 Create zombie resources for demonstration
│   ├── garbage_collect.py              Python/Boto3 zombie asset detector + cleaner
│   ├── garbage_collect.sh              Bash/AWS CLI version of the same
│   ├── analyze_costs.py                Cost Explorer spend breakdown + forecasting
│   └── tag_compliance_check.py         Tag policy compliance auditor
├── governance/
│   ├── budget_alert.yaml               CloudFormation: AWS Budget + SNS email alerts
│   ├── config_tagging_rule.yaml        CloudFormation: AWS Config required-tags rule
│   ├── scp_require_tag.json            Service Control Policy: deny launch without tags
│   └── tagging_policy.md              Org tagging policy document
├── infrastructure/
│   └── asg_mixed_instances.yaml        CloudFormation: ASG with Spot + On-Demand mix
├── docs/
│   ├── cost_optimization_guide.md      End-to-end AWS cost optimisation guide
│   ├── walkthrough.md                  Live demo walkthrough script
│   └── findings/                       Screenshots from the audit
└── Makefile                            Convenience targets for common operations
```

---

## Quick Start

### Prerequisites

```bash
# AWS CLI v2
aws --version

# Python 3.10+ and boto3
python3 --version
pip install boto3

# jq (for Bash script)
jq --version

# Verify AWS credentials
aws sts get-caller-identity
```

### 1. Create demo zombie resources

```bash
python scripts/setup_sandbox.py --region us-east-1 --no-ec2
```

### 2. Detect zombie assets

```bash
# Python version (dry-run — safe)
python scripts/garbage_collect.py --region us-east-1

# Bash version
bash scripts/garbage_collect.sh --region us-east-1
```

### 3. Analyse costs

```bash
python scripts/analyze_costs.py --region us-east-1 --days 30
```

### 4. Check tag compliance

```bash
python scripts/tag_compliance_check.py --region us-east-1
```

### 5. Clean up zombie assets

```bash
python scripts/garbage_collect.py --region us-east-1 --delete
```

### 6. Deploy governance controls

```bash
# Budget + SNS alerts
aws cloudformation deploy \
  --template-file governance/budget_alert.yaml \
  --stack-name cost-detective-budget \
  --parameter-overrides AlertEmail=you@company.com BudgetLimitUSD=50 \
  --capabilities CAPABILITY_NAMED_IAM

# AWS Config required-tags rule
aws cloudformation deploy \
  --template-file governance/config_tagging_rule.yaml \
  --stack-name cost-detective-config \
  --parameter-overrides AlertEmail=you@company.com EnableConfigRecorder=false \
  --capabilities CAPABILITY_NAMED_IAM
```

### 7. Deploy cost-optimised ASG

```bash
aws cloudformation deploy \
  --template-file infrastructure/asg_mixed_instances.yaml \
  --stack-name cost-detective-asg \
  --parameter-overrides \
    CostCenter=ENG-001 \
    Environment=dev \
    Project=cost-detective \
    MinCapacity=1 MaxCapacity=6 \
    OnDemandBaseCapacity=1 \
    OnDemandPercentageAboveBase=25 \
  --capabilities CAPABILITY_NAMED_IAM
```

Or use `make`:

```bash
make sandbox EMAIL=you@company.com   # create demo resources + deploy all controls
make scan                            # run all analysis scripts
make clean-stacks                    # delete all CloudFormation stacks
```

---

## Objectives Covered

### 1. Analysis and Cleanup
- [x] `setup_sandbox.py` — creates unattached EBS volumes, unused EIPs, idle EC2 instances
- [x] Trusted Advisor integration documented in walkthrough
- [x] `garbage_collect.py` (Python/Boto3) — detects and deletes zombie assets
- [x] `garbage_collect.sh` (Bash/AWS CLI) — alternate implementation
- [x] `analyze_costs.py` — Cost Explorer spend breakdown and forecasting

### 2. Governance
- [x] `budget_alert.yaml` — AWS Budget with SNS/email alerts at 80%, 100% actual and 100% forecasted
- [x] `config_tagging_rule.yaml` — AWS Config required-tags rule (EC2 + EBS)
- [x] `scp_require_tag.json` — Service Control Policy preventing launch without CostCenter tag
- [x] `tagging_policy.md` — complete tagging policy documentation with remediation process
- [x] `tag_compliance_check.py` — automated compliance auditor

### 3. Optimisation Architecture
- [x] `asg_mixed_instances.yaml` — ASG with Mixed Instances Policy (On-Demand base + Spot scaling)
- [x] `cost_optimization_guide.md` — end-to-end practical guide (Identify → Govern → Optimise → Monitor)
- [x] `walkthrough.md` — live demo script for submission walkthrough

---

## Financial Impact

| Category | Before | After | Savings |
|---|---|---|---|
| Zombie EC2 + EBS + EIPs | $91.12/month | $0 | $91.12/month |
| EC2 (right-sized + Spot) | $69.12/month | $36.44/month | $32.68/month |
| Data transfer (VPC endpoints) | $9.20/month | $2.30/month | $6.90/month |
| S3 (Intelligent-Tiering) | $8.50/month | $5.10/month | $3.40/month |
| **TOTAL** | **$177.94/month** | **$43.84/month** | **$134.10/month** |

**Annual savings: ~$1,609**

---

## Key Design Decisions

**Dual-language scripts (Python + Bash):** The garbage collector is implemented in both Python/Boto3 and Bash/AWS CLI to accommodate teams that may not have Python in their environment or may want to embed the check in CI pipelines that use shell.

**Dry-run by default:** All deletion scripts default to dry-run. Destructive operations require either `--delete` (interactive) or `--delete --force` (CI mode).

**CloudFormation for governance:** All controls are deployed via CloudFormation, making them version-controlled, reproducible, and auditable. No manual console clicking.

**Spot diversification:** The ASG specifies 7 instance type overrides to maximise Spot pool availability and minimise interruption probability.

**IMDSv2 enforced:** The Launch Template mandates `HttpTokens: required` — prevents SSRF attacks from accessing instance metadata.

---

## Documentation

- [Audit Report](AUDIT_REPORT.md) — full findings, financial impact, remediation
- [Tagging Policy](governance/tagging_policy.md) — mandatory tags, enforcement layers, remediation process
- [Cost Optimisation Guide](docs/cost_optimization_guide.md) — end-to-end guide (Identify → Govern → Optimise → Monitor)
- [Walkthrough](docs/walkthrough.md) — live demo script

---

## Makefile Targets

```
make help           Show all available targets
make scan           Run analysis scripts (dry-run)
make sandbox        Create zombie resources for demo
make delete         Clean up zombie assets
make deploy-budget  Deploy budget alert stack
make deploy-config  Deploy Config tagging rule stack
make deploy-asg     Deploy ASG Mixed Instances stack
make clean-sandbox  Delete sandbox resources
make clean-stacks   Delete all CloudFormation stacks
```
