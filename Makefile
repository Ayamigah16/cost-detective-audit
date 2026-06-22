# =============================================================================
# Cost Detective — Makefile
# =============================================================================
# Convenience targets for common audit and governance operations.
#
# Required env vars (set via environment or .env):
#   AWS_DEFAULT_REGION  (default: us-east-1)
#   EMAIL               email address for budget/config alerts
#
# Optional:
#   AWS_PROFILE         named AWS CLI profile
#   BUDGET_LIMIT        monthly budget threshold in USD (default: 50)
#   ENVIRONMENT         dev | staging | prod (default: dev)
#   COST_CENTER         cost centre tag value (default: ENG-001)
# =============================================================================

REGION        ?= $(or $(AWS_DEFAULT_REGION), us-east-1)
EMAIL         ?= platform@company.com
BUDGET_LIMIT  ?= 50
ENVIRONMENT   ?= dev
COST_CENTER   ?= ENG-001
PROJECT       ?= cost-detective
PROFILE_ARGS  := $(if $(AWS_PROFILE),--profile $(AWS_PROFILE),)

PYTHON        := python3
AWS           := aws $(PROFILE_ARGS)

BUDGET_STACK  := cost-detective-budget
CONFIG_STACK  := cost-detective-config
ASG_STACK     := cost-detective-asg

.PHONY: help scan sandbox delete deploy-budget deploy-config deploy-asg \
        clean-sandbox clean-stacks status

# ── Help ──────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Cost Detective — Available Targets"
	@echo "  ════════════════════════════════════════════════════════"
	@echo ""
	@echo "  Analysis:"
	@echo "    scan              Run all analysis scripts (dry-run, safe)"
	@echo "    analyze           Run cost analysis via Cost Explorer"
	@echo "    tag-check         Run tag compliance check"
	@echo ""
	@echo "  Demo:"
	@echo "    sandbox           Create zombie resources for demonstration"
	@echo "    delete            Delete zombie assets (garbage collect)"
	@echo "    clean-sandbox     Remove sandbox resources using state file"
	@echo ""
	@echo "  Governance:"
	@echo "    deploy-budget     Deploy AWS Budget + SNS alert stack"
	@echo "    deploy-config     Deploy AWS Config required-tags rule stack"
	@echo "    deploy-asg        Deploy Auto Scaling Group (Spot + On-Demand)"
	@echo "    clean-stacks      Delete all CloudFormation stacks"
	@echo ""
	@echo "  Info:"
	@echo "    status            Show status of all stacks"
	@echo ""
	@echo "  Config: REGION=$(REGION) EMAIL=$(EMAIL) BUDGET=$(BUDGET_LIMIT)"
	@echo ""

# ── Analysis ──────────────────────────────────────────────────────────────
scan:
	@echo "==> Scanning for zombie assets (dry-run)..."
	$(PYTHON) scripts/garbage_collect.py --region $(REGION)
	@echo ""
	@echo "==> Checking tag compliance..."
	$(PYTHON) scripts/tag_compliance_check.py --region $(REGION)

analyze:
	@echo "==> Analyzing costs via Cost Explorer..."
	$(PYTHON) scripts/analyze_costs.py --region $(REGION) --days 30

tag-check:
	@echo "==> Running tag compliance check..."
	$(PYTHON) scripts/tag_compliance_check.py --region $(REGION)

# ── Demo ──────────────────────────────────────────────────────────────────
sandbox:
	@echo "==> Creating zombie sandbox resources..."
	$(PYTHON) scripts/setup_sandbox.py --region $(REGION) --no-ec2

sandbox-full:
	@echo "==> Creating zombie sandbox resources (including EC2)..."
	$(PYTHON) scripts/setup_sandbox.py --region $(REGION)

delete:
	@echo "==> Garbage collecting zombie assets..."
	$(PYTHON) scripts/garbage_collect.py --region $(REGION) --delete

delete-force:
	@echo "==> Force-deleting zombie assets (no confirmation)..."
	$(PYTHON) scripts/garbage_collect.py --region $(REGION) --delete --force

clean-sandbox:
	@echo "==> Cleaning up sandbox resources from state file..."
	$(PYTHON) scripts/setup_sandbox.py --region $(REGION) --cleanup

# ── Governance Deployment ─────────────────────────────────────────────────
deploy-budget:
	@echo "==> Deploying AWS Budget + SNS alert stack..."
	$(AWS) cloudformation deploy \
		--template-file governance/budget_alert.yaml \
		--stack-name $(BUDGET_STACK) \
		--region $(REGION) \
		--parameter-overrides \
			AlertEmail=$(EMAIL) \
			BudgetLimitUSD=$(BUDGET_LIMIT) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-fail-on-empty-changeset
	@echo "==> Budget stack deployed. Check email for SNS subscription confirmation."

deploy-config:
	@echo "==> Deploying AWS Config required-tags rule..."
	$(AWS) cloudformation deploy \
		--template-file governance/config_tagging_rule.yaml \
		--stack-name $(CONFIG_STACK) \
		--region $(REGION) \
		--parameter-overrides \
			AlertEmail=$(EMAIL) \
			EnableConfigRecorder=false \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-fail-on-empty-changeset
	@echo "==> Config stack deployed. Rule: cost-detective-required-tags"

deploy-asg:
	@echo "==> Deploying Auto Scaling Group with Mixed Instances Policy..."
	$(AWS) cloudformation deploy \
		--template-file infrastructure/asg_mixed_instances.yaml \
		--stack-name $(ASG_STACK) \
		--region $(REGION) \
		--parameter-overrides \
			CostCenter=$(COST_CENTER) \
			Environment=$(ENVIRONMENT) \
			Project=$(PROJECT) \
			MinCapacity=1 \
			MaxCapacity=6 \
			OnDemandBaseCapacity=1 \
			OnDemandPercentageAboveBase=25 \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-fail-on-empty-changeset
	@echo "==> ASG stack deployed."
	$(AWS) cloudformation describe-stacks \
		--stack-name $(ASG_STACK) \
		--region $(REGION) \
		--query 'Stacks[0].Outputs' \
		--output table

deploy-all: deploy-budget deploy-config deploy-asg
	@echo "==> All governance stacks deployed."

# ── Cleanup ───────────────────────────────────────────────────────────────
clean-stacks:
	@echo "==> Deleting CloudFormation stacks..."
	-$(AWS) cloudformation delete-stack --stack-name $(ASG_STACK)    --region $(REGION)
	-$(AWS) cloudformation delete-stack --stack-name $(CONFIG_STACK) --region $(REGION)
	-$(AWS) cloudformation delete-stack --stack-name $(BUDGET_STACK) --region $(REGION)
	@echo "==> Stacks queued for deletion. Run 'make status' to monitor."

# ── Status ────────────────────────────────────────────────────────────────
status:
	@echo "==> CloudFormation Stack Status ($(REGION)):"
	$(AWS) cloudformation describe-stacks \
		--region $(REGION) \
		--query 'Stacks[?contains(`["$(BUDGET_STACK)","$(CONFIG_STACK)","$(ASG_STACK)"]`, StackName)].{Name:StackName,Status:StackStatus}' \
		--output table 2>/dev/null || echo "  No matching stacks found."

	@echo ""
	@echo "==> Zombie Asset Summary ($(REGION)):"
	@echo "  Unattached EBS volumes:"
	@$(AWS) ec2 describe-volumes \
		--region $(REGION) \
		--filters Name=status,Values=available \
		--query 'length(Volumes)' \
		--output text | xargs -I{} echo "    {} volume(s)"
	@echo "  Unassociated Elastic IPs:"
	@$(AWS) ec2 describe-addresses \
		--region $(REGION) \
		--query 'length(Addresses[?AssociationId==null])' \
		--output text | xargs -I{} echo "    {} EIP(s)"
