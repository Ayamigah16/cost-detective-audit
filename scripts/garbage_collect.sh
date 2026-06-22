#!/usr/bin/env bash
# =============================================================================
# Cost Detective - Zombie Asset Garbage Collector (Bash / AWS CLI)
# =============================================================================
# Identifies and optionally removes:
#   - EBS volumes in 'available' state (unattached)
#   - Elastic IPs with no association
#
# Usage:
#   ./garbage_collect.sh                  # Dry-run (default — safe)
#   ./garbage_collect.sh --delete         # Actually delete resources
#   ./garbage_collect.sh --region eu-west-1
#   ./garbage_collect.sh --region us-east-1 --delete --force   # CI mode
#
# Prerequisites: AWS CLI v2, jq
# =============================================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────
REGION="us-east-1"
DELETE=false
FORCE=false
REPORT_FILE="garbage_collect_report_$(date -u +%Y%m%dT%H%M%S).json"

EBS_PRICE_GP2=0.10
EBS_PRICE_GP3=0.08
EBS_PRICE_IO1=0.125
EIP_PRICE_MONTH=3.60

TOTAL_VOLUMES=0
TOTAL_EIPS=0
TOTAL_WASTE=0

# ── Colour helpers ────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
log_error() { echo -e "${RED}[ERR]${NC}  $*" >&2; }
separator() { printf '%0.s─' {1..64}; echo; }

# ── Argument parsing ──────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)   REGION="$2"; shift 2 ;;
    --delete)   DELETE=true; shift ;;
    --force)    FORCE=true; shift ;;
    --output)   REPORT_FILE="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | head -20 | sed 's/^# \{0,2\}//'
      exit 0
      ;;
    *) log_error "Unknown argument: $1"; exit 1 ;;
  esac
done

# ── Preflight checks ──────────────────────────────────────────────────────
for cmd in aws jq bc; do
  if ! command -v "$cmd" &>/dev/null; then
    log_error "Required tool not found: $cmd"
    exit 1
  fi
done

MODE_LABEL="DRY-RUN"
[[ "$DELETE" == true ]] && MODE_LABEL="${RED}DELETE${NC}"

echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         COST DETECTIVE — Zombie Asset Garbage Collector      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo -e "  Region : ${CYAN}${REGION}${NC}"
echo -e "  Mode   : ${MODE_LABEL}"
echo

# ── EBS Volume scan ───────────────────────────────────────────────────────
separator
echo -e "${BOLD}  UNATTACHED EBS VOLUMES${NC}"
separator

VOLUMES_JSON=$(aws ec2 describe-volumes \
  --region "$REGION" \
  --filters Name=status,Values=available \
  --query 'Volumes[*].{ID:VolumeId,Size:Size,Type:VolumeType,AZ:AvailabilityZone,CreateTime:CreateTime,Tags:Tags}' \
  --output json)

VOLUME_COUNT=$(echo "$VOLUMES_JSON" | jq 'length')
TOTAL_VOLUMES=$VOLUME_COUNT

if [[ "$VOLUME_COUNT" -eq 0 ]]; then
  log_ok "No unattached EBS volumes found."
else
  echo
  VOLUME_WASTE=0
  VOLUME_IDS=()

  while IFS= read -r vol; do
    VOL_ID=$(echo "$vol" | jq -r '.ID')
    VOL_SIZE=$(echo "$vol" | jq -r '.Size')
    VOL_TYPE=$(echo "$vol" | jq -r '.Type')
    VOL_AZ=$(echo "$vol" | jq -r '.AZ')
    VOL_CREATE=$(echo "$vol" | jq -r '.CreateTime // "unknown"')
    VOL_NAME=$(echo "$vol" | jq -r '.Tags[]? | select(.Key=="Name") | .Value' 2>/dev/null || echo "(no name)")

    # Estimate monthly cost
    case "$VOL_TYPE" in
      gp3) RATE=$EBS_PRICE_GP3 ;;
      io1|io2) RATE=$EBS_PRICE_IO1 ;;
      *) RATE=$EBS_PRICE_GP2 ;;
    esac
    VOL_COST=$(echo "$VOL_SIZE * $RATE" | bc)
    VOLUME_WASTE=$(echo "$VOLUME_WASTE + $VOL_COST" | bc)

    echo -e "  ${YELLOW}${VOL_ID}${NC}  ${VOL_NAME}"
    echo    "    Type: ${VOL_TYPE} | Size: ${VOL_SIZE} GB | AZ: ${VOL_AZ}"
    echo    "    Created: ${VOL_CREATE}"
    printf  "    Est. waste: \$%.2f/month\n" "$VOL_COST"
    echo

    VOLUME_IDS+=("$VOL_ID")
  done < <(echo "$VOLUMES_JSON" | jq -c '.[]')

  printf "  ► ${VOLUME_COUNT} zombie volumes = \$%.2f/month wasted\n" "$VOLUME_WASTE"
  TOTAL_WASTE=$(echo "$TOTAL_WASTE + $VOLUME_WASTE" | bc)
fi

# ── Elastic IP scan ───────────────────────────────────────────────────────
separator
echo -e "${BOLD}  UNASSOCIATED ELASTIC IPs${NC}"
separator

EIPS_JSON=$(aws ec2 describe-addresses \
  --region "$REGION" \
  --query 'Addresses[?AssociationId==null].{AllocationId:AllocationId,PublicIp:PublicIp,Domain:Domain,Tags:Tags}' \
  --output json)

EIP_COUNT=$(echo "$EIPS_JSON" | jq 'length')
TOTAL_EIPS=$EIP_COUNT

if [[ "$EIP_COUNT" -eq 0 ]]; then
  log_ok "No unassociated Elastic IPs found."
else
  echo
  EIP_IDS=()
  while IFS= read -r eip; do
    ALLOC_ID=$(echo "$eip" | jq -r '.AllocationId // "N/A"')
    PUBLIC_IP=$(echo "$eip" | jq -r '.PublicIp')
    DOMAIN=$(echo "$eip" | jq -r '.Domain')

    echo -e "  ${YELLOW}${PUBLIC_IP}${NC}  (${ALLOC_ID})"
    echo    "    Domain: ${DOMAIN}"
    printf  "    Est. waste: \$%.2f/month\n" "$EIP_PRICE_MONTH"
    echo

    EIP_IDS+=("$ALLOC_ID")
  done < <(echo "$EIPS_JSON" | jq -c '.[]')

  EIP_WASTE=$(echo "$EIP_COUNT * $EIP_PRICE_MONTH" | bc)
  printf "  ► ${EIP_COUNT} unused EIPs = \$%.2f/month wasted\n" "$EIP_WASTE"
  TOTAL_WASTE=$(echo "$TOTAL_WASTE + $EIP_WASTE" | bc)
fi

# ── Summary ───────────────────────────────────────────────────────────────
separator
printf "  ${BOLD}TOTAL MONTHLY WASTE  :${NC} \$%.2f\n" "$TOTAL_WASTE"
printf "  ${BOLD}TOTAL ANNUAL WASTE   :${NC} \$%.2f\n" "$(echo "$TOTAL_WASTE * 12" | bc)"
separator
echo

# ── Delete phase ──────────────────────────────────────────────────────────
if [[ "$DELETE" == true ]]; then
  TOTAL_RESOURCES=$((VOLUME_COUNT + EIP_COUNT))
  if [[ "$TOTAL_RESOURCES" -eq 0 ]]; then
    log_ok "Nothing to delete — environment is clean."
    exit 0
  fi

  if [[ "$FORCE" != true ]]; then
    echo -e "${RED}WARNING: About to permanently delete ${TOTAL_RESOURCES} resource(s).${NC}"
    echo -n "  Type 'DELETE' to confirm: "
    read -r CONFIRM
    if [[ "$CONFIRM" != "DELETE" ]]; then
      log_warn "Deletion cancelled by user."
      exit 0
    fi
  fi

  # Delete EBS volumes
  DELETED_VOLS=0
  for VOL_ID in "${VOLUME_IDS[@]+"${VOLUME_IDS[@]}"}"; do
    if aws ec2 delete-volume --region "$REGION" --volume-id "$VOL_ID" 2>/dev/null; then
      log_ok "Deleted volume: $VOL_ID"
      ((DELETED_VOLS++)) || true
    else
      log_error "Failed to delete volume: $VOL_ID"
    fi
  done

  # Release Elastic IPs
  RELEASED_EIPS=0
  for ALLOC_ID in "${EIP_IDS[@]+"${EIP_IDS[@]}"}"; do
    if aws ec2 release-address --region "$REGION" --allocation-id "$ALLOC_ID" 2>/dev/null; then
      log_ok "Released EIP: $ALLOC_ID"
      ((RELEASED_EIPS++)) || true
    else
      log_error "Failed to release EIP: $ALLOC_ID"
    fi
  done

  separator
  log_ok "Cleanup complete: ${DELETED_VOLS} volume(s) deleted, ${RELEASED_EIPS} EIP(s) released."
else
  echo -e "${CYAN}DRY-RUN mode: no resources were modified.${NC}"
  echo    "  Re-run with --delete to remove zombie assets."
fi

# ── JSON report ───────────────────────────────────────────────────────────
jq -n \
  --argjson volumes "$VOLUMES_JSON" \
  --argjson eips "$EIPS_JSON" \
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg region "$REGION" \
  --argjson waste "$TOTAL_WASTE" \
  '{
    generated_at: $timestamp,
    region: $region,
    findings: {
      unattached_volumes: ($volumes | length),
      unassociated_eips: ($eips | length),
      total_monthly_waste_usd: $waste,
      total_annual_waste_usd: ($waste * 12)
    },
    resources: {
      volumes: $volumes,
      eips: $eips
    }
  }' > "$REPORT_FILE"

echo
log_info "Report saved: ${REPORT_FILE}"
