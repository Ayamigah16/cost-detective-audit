# Screenshots — Findings Evidence

Place screenshots here during the live walkthrough or sandbox execution.

## Required Screenshots

| File | What to capture |
|---|---|
| `cost_explorer_service_breakdown.png` | Cost Explorer → last 30 days → grouped by Service |
| `cost_explorer_untagged_spend.png` | Cost Explorer → Group by Tag → CostCenter → shows blank/untagged |
| `trusted_advisor_cost_checks.png` | Trusted Advisor → Cost Optimization → all checks |
| `trusted_advisor_idle_ec2.png` | Trusted Advisor → Low Utilization EC2 → idle instance detail |
| `trusted_advisor_eips.png` | Trusted Advisor → Unassociated EIPs finding |
| `garbage_collect_output.png` | Terminal output of `garbage_collect.py` dry-run |
| `tag_compliance_output.png` | Terminal output of `tag_compliance_check.py` |
| `aws_budget_dashboard.png` | AWS Console → Billing → Budgets → budget details |
| `config_compliance_dashboard.png` | AWS Console → Config → Rules → required-tags compliance |
| `asg_instances_console.png` | AWS Console → EC2 → Auto Scaling Groups → Instance Management tab |
| `asg_spot_instances.png` | EC2 Instances list filtered to show spot vs normal lifecycle |

## Screenshot Instructions

1. Run `python scripts/setup_sandbox.py --region us-east-1` to create demo resources
2. Navigate to each AWS Console section above and capture screenshot
3. Save files into this directory with the exact filenames in the table
4. Run the scripts and capture terminal output (use `| tee screenshot_output.txt` to save)
5. Reference these files in `AUDIT_REPORT.md`

## Tips for Good Screenshots

- Use browser zoom at 90% for wider captures
- Annotate with a red box or arrow on key findings
- Include the browser URL bar so reviewers can reproduce the navigation path
- Capture timestamp visible (bottom of screen or AWS console timestamp)
