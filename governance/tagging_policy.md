# AWS Resource Tagging Policy

**Version:** 1.2  
**Effective Date:** 2026-06-22  
**Owner:** Platform / FinOps Team  
**Enforcement:** AWS Config (detective) + SCP (preventive)

---

## 1. Purpose

This policy defines the mandatory tags that must be applied to all AWS resources at creation time. Tags are the foundation of:

- **Cost allocation** — chargeback reports to business units
- **Security posture** — isolate resources by environment in IAM conditions
- **Operational hygiene** — identify owners of orphaned resources during incidents
- **Compliance audits** — demonstrate policy adherence to auditors

Without consistent tagging, the organisation cannot attribute costs to teams, cannot enforce least-privilege IAM policies by environment, and cannot rapidly contact owners of misbehaving resources.

---

## 2. Mandatory Tags

These tags are **required on all EC2 instances and EBS volumes**. The AWS Config rule `cost-detective-required-tags` evaluates compliance continuously.

| Tag Key | Description | Example Values | Enforced By |
|---|---|---|---|
| `CostCenter` | Billing chargeback unit code | `ENG-001`, `INFRA-002`, `DATA-003` | SCP + Config |
| `Environment` | Deployment tier | `prod`, `staging`, `dev`, `sandbox` | SCP + Config |
| `Project` | Owning project or product | `platform`, `checkout`, `ml-pipeline` | Config |
| `Owner` | Team email or individual email | `platform@company.com` | Config |

### 2.1 Extended Tags (recommended, not enforced)

| Tag Key | Description | Example |
|---|---|---|
| `Name` | Human-readable resource name | `api-server-01` |
| `AutoShutdown` | Tag for scheduled stop automation | `true` / `false` |
| `DataClassification` | Sensitivity of data stored | `public`, `internal`, `confidential` |
| `Terraform` | Whether resource is IaC-managed | `true` |
| `Expiry` | Sandbox/temporary resource expiry | `2026-12-31` |

---

## 3. Allowed Tag Values

### `Environment`
Allowed values (case-insensitive):

```
prod | production
staging | stage
dev | development
test
sandbox
```

Any other value will be flagged as a policy violation.

### `CostCenter`
Format: `TEAM-NNN` where `TEAM` is the 2–8 character team abbreviation and `NNN` is a three-digit number assigned by Finance.

```
ENG-001   Engineering
INFRA-002 Infrastructure / Platform
DATA-003  Data Science
SEC-004   Security
OPS-005   Operations
```

---

## 4. Scope

| Resource Type | Mandatory Tagging |
|---|---|
| EC2 Instances | Yes |
| EBS Volumes | Yes |
| Elastic Load Balancers | Yes |
| RDS Instances | Yes |
| S3 Buckets | Yes |
| Lambda Functions | Yes |
| Elastic IPs | Yes |
| NAT Gateways | Yes |
| CloudFormation Stacks | Yes (tags propagate to child resources) |
| VPCs, Subnets | Recommended |
| IAM Roles | Recommended |
| Security Groups | Recommended |

---

## 5. Enforcement Layers

### Layer 1 — Preventive: Service Control Policy (SCP)

The SCP at `governance/scp_require_tag.json` is attached at the OU level.

**Effect:** Any `ec2:RunInstances` call that does not include `CostCenter` **and** `Environment` in `aws:RequestTag` is denied with `UnauthorizedOperation`.

**Exceptions (listed in the SCP ArnNotLike condition):**
- `CloudFormationServiceRole` — CloudFormation deployments (tags must be in the template)
- `BreakGlassAdmin` — emergency access role
- `OrganizationAccountAccessRole` — cross-account admin
- AWS service-linked roles

> **Note:** Always propagate tags from CloudFormation stacks using `TagSpecifications` in launch templates and `PropagateAtLaunch: true` in Auto Scaling groups.

### Layer 2 — Detective: AWS Config Rule

The `required-tags` managed Config rule continuously evaluates all in-scope resources. Non-compliant resources appear in the Config dashboard within minutes of creation.

CloudFormation stack: `governance/config_tagging_rule.yaml`

### Layer 3 — Reporting: Tag Compliance Script

The script `scripts/tag_compliance_check.py` generates a point-in-time compliance report across EC2 instances, EBS volumes, Elastic IPs, and security groups. Intended for weekly FinOps reviews.

```bash
python scripts/tag_compliance_check.py --region us-east-1 --output report.json
```

---

## 6. Remediation Process

When a non-compliant resource is detected:

| Timeline | Action |
|---|---|
| T+0 | Config flags resource as NON_COMPLIANT; EventBridge fires |
| T+0 | SNS email sent to team alias |
| T+24h | Resource owner receives Jira ticket to apply missing tags |
| T+72h | If unresolved: escalation to engineering manager |
| T+7d | If still unresolved: resource is quarantined (IAM deny all) |
| T+14d | Resource eligible for deletion if still untagged and idle |

### Manual Remediation

```bash
aws ec2 create-tags \
  --resources i-0123456789abcdef0 \
  --tags Key=CostCenter,Value=ENG-001 \
        Key=Environment,Value=dev \
        Key=Project,Value=platform \
        Key=Owner,Value=platform@company.com
```

### Bulk Auto-remediation Dry-run

```bash
python scripts/tag_compliance_check.py --fix-dryrun
```

---

## 7. Cost Allocation and Reporting

With tags consistently applied, enable the following:

1. **Cost Allocation Tags** — In Billing Console → Cost allocation tags → Activate `CostCenter`, `Environment`, `Project`
2. **Cost Explorer Group By Tag** — Visualise spend per `CostCenter` or `Project`
3. **Monthly Chargeback Report** — Export Cost and Usage Report (CUR) to S3, query via Athena grouped by `CostCenter`

---

## 8. Tag Governance Cadence

| Frequency | Activity |
|---|---|
| Daily | AWS Config evaluates all resources automatically |
| Weekly | FinOps team reviews compliance dashboard; scripts/tag_compliance_check.py run |
| Monthly | Cost allocation report generated per CostCenter; budget vs actuals reviewed |
| Quarterly | Tag taxonomy reviewed; new projects added; retired CostCenter codes removed |

---

## 9. FAQ

**Q: My CloudFormation template already applies tags. Do I need to do anything else?**  
A: If your template includes `TagSpecifications` on EC2 resources and `PropagateAtLaunch: true` on ASG tags, and the stack itself is tagged, you are compliant. Verify with `tag_compliance_check.py` after deployment.

**Q: My Terraform module doesn't support all tag keys.**  
A: Add a `default_tags` block to your Terraform provider configuration — this applies tags to all resources managed by that provider without modifying every module.

```hcl
provider "aws" {
  default_tags {
    tags = {
      CostCenter  = var.cost_center
      Environment = var.environment
      Project     = var.project
      Owner       = "platform@company.com"
    }
  }
}
```

**Q: Can I override the SCP for a one-off test?**  
A: Use the sandbox account, which has relaxed SCPs. Never modify SCP exceptions for production accounts without a change request approved by the Security team.

**Q: What about resources launched before this policy was adopted?**  
A: Legacy resources are exempt from SCP enforcement (they already exist) but are still flagged by AWS Config. Use the bulk remediation script to catch up on a schedule agreed with Finance.
