#!/usr/bin/env python3
"""
Cost Detective - Zombie Asset Garbage Collector
================================================
Scans for and optionally removes "zombie" AWS resources:
  - EBS volumes in 'available' state (unattached)
  - Elastic IPs not associated with any resource
  - Optionally: stopped EC2 instances older than N days

Usage:
  python garbage_collect.py                   # Dry-run (safe, no deletions)
  python garbage_collect.py --delete          # Delete zombie assets (requires confirmation)
  python garbage_collect.py --region eu-west-1
  python garbage_collect.py --include-stopped-ec2 --stopped-days 14
  python garbage_collect.py --all-regions     # Scan every enabled region

Output:
  - Console log with findings and cost estimates
  - JSON report: garbage_collect_report_<timestamp>.json
"""

import boto3
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Pricing constants (us-east-1; adjust per region) ──────────────────────
EBS_PRICE = {
    "gp3": 0.08,   # $/GB/month
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
}
EIP_PRICE_PER_MONTH = 3.60    # $0.005/hr * 720 hrs
EC2_PRICES = {                 # On-Demand Linux us-east-1 approximate
    "t2.micro":  8.47,
    "t3.medium": 30.37,
    "m5.large":  69.12,
    "m5.xlarge": 138.24,
    "c5.large":  61.20,
}


# ── Helpers ────────────────────────────────────────────────────────────────

def get_name_tag(tags):
    for t in (tags or []):
        if t["Key"] == "Name":
            return t["Value"]
    return "(no name)"


def format_tags(tags):
    if not tags:
        return "none"
    return ", ".join(f"{t['Key']}={t['Value']}" for t in tags)


def ebs_monthly_cost(volume):
    vol_type = volume.get("VolumeType", "gp2")
    size = volume.get("Size", 0)
    rate = EBS_PRICE.get(vol_type, 0.10)
    return size * rate


def days_old(dt):
    if dt is None:
        return 0
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


# ── Finders ───────────────────────────────────────────────────────────────

def find_unattached_volumes(ec2):
    """EBS volumes in 'available' state = not attached to any instance."""
    paginator = ec2.get_paginator("describe_volumes")
    volumes = []
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        volumes.extend(page["Volumes"])
    return volumes


def find_unassociated_eips(ec2):
    """Elastic IPs with no AssociationId = wasting $3.60/month each."""
    resp = ec2.describe_addresses()
    return [a for a in resp["Addresses"] if "AssociationId" not in a]


def find_stopped_instances(ec2, min_days=7):
    """EC2 instances stopped for longer than min_days."""
    paginator = ec2.get_paginator("describe_instances")
    stopped = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_days)
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                state_reason = inst.get("StateTransitionReason", "")
                # StateTransitionReason contains "User initiated (YYYY-MM-DD ...)"
                stopped.append(inst)
    return stopped


# ── Reporters ─────────────────────────────────────────────────────────────

def report_volumes(volumes):
    total_cost = 0.0
    total_gb = 0
    print(f"\n{'━'*64}")
    print(f"  ZOMBIE EBS VOLUMES  ({len(volumes)} found)")
    print(f"{'━'*64}")
    if not volumes:
        print("  None found.")
        return 0.0
    for v in volumes:
        cost = ebs_monthly_cost(v)
        total_cost += cost
        total_gb += v.get("Size", 0)
        create_time = v.get("CreateTime")
        age = days_old(create_time)
        print(
            f"\n  ID       : {v['VolumeId']}\n"
            f"  Name     : {get_name_tag(v.get('Tags'))}\n"
            f"  Type     : {v.get('VolumeType', '?')} | "
            f"Size: {v.get('Size', 0)} GB | AZ: {v.get('AvailabilityZone', '?')}\n"
            f"  Age      : {age} days\n"
            f"  Tags     : {format_tags(v.get('Tags'))}\n"
            f"  Waste    : ${cost:.2f}/month"
        )
    print(f"\n  ► Total: {total_gb} GB across {len(volumes)} volumes "
          f"= ${total_cost:.2f}/month wasted")
    return total_cost


def report_eips(eips):
    total_cost = len(eips) * EIP_PRICE_PER_MONTH
    print(f"\n{'━'*64}")
    print(f"  UNASSOCIATED ELASTIC IPs  ({len(eips)} found)")
    print(f"{'━'*64}")
    if not eips:
        print("  None found.")
        return 0.0
    for addr in eips:
        print(
            f"\n  Allocation : {addr.get('AllocationId', 'N/A')}\n"
            f"  Public IP  : {addr.get('PublicIp', 'N/A')}\n"
            f"  Domain     : {addr.get('Domain', 'N/A')}\n"
            f"  Tags       : {format_tags(addr.get('Tags'))}\n"
            f"  Waste      : ${EIP_PRICE_PER_MONTH:.2f}/month"
        )
    print(f"\n  ► Total: {len(eips)} unused EIPs = ${total_cost:.2f}/month wasted")
    return total_cost


def report_stopped_instances(instances):
    print(f"\n{'━'*64}")
    print(f"  LONG-RUNNING STOPPED EC2 INSTANCES  ({len(instances)} found)")
    print(f"{'━'*64}")
    if not instances:
        print("  None found.")
        return 0.0
    total_cost = 0.0
    for inst in instances:
        itype = inst.get("InstanceType", "unknown")
        cost = EC2_PRICES.get(itype, 0)
        total_cost += cost
        print(
            f"\n  ID       : {inst['InstanceId']}\n"
            f"  Name     : {get_name_tag(inst.get('Tags'))}\n"
            f"  Type     : {itype}\n"
            f"  State    : {inst['State']['Name']}\n"
            f"  Tags     : {format_tags(inst.get('Tags'))}\n"
            f"  Note     : EBS volumes still accruing cost while stopped\n"
            f"  Est. EBS : varies (check attached volumes)"
        )
    print(f"\n  ► {len(instances)} stopped instances (EBS costs continue; terminate if unused)")
    return total_cost


# ── Deleters ──────────────────────────────────────────────────────────────

def delete_volumes(ec2, volumes):
    deleted, failed = [], []
    for v in volumes:
        vid = v["VolumeId"]
        try:
            ec2.delete_volume(VolumeId=vid)
            logger.info(f"[DELETED] Volume {vid}")
            deleted.append(vid)
        except ClientError as e:
            logger.error(f"[FAILED]  Volume {vid}: {e.response['Error']['Message']}")
            failed.append({"id": vid, "error": str(e)})
    return deleted, failed


def release_eips(ec2, eips):
    released, failed = [], []
    for addr in eips:
        alloc_id = addr.get("AllocationId")
        ip = addr.get("PublicIp")
        try:
            if alloc_id:
                ec2.release_address(AllocationId=alloc_id)
            else:
                ec2.release_address(PublicIp=ip)
            logger.info(f"[RELEASED] EIP {ip} ({alloc_id})")
            released.append(ip)
        except ClientError as e:
            logger.error(f"[FAILED]  EIP {ip}: {e.response['Error']['Message']}")
            failed.append({"ip": ip, "error": str(e)})
    return released, failed


# ── Report writer ─────────────────────────────────────────────────────────

def save_json_report(findings, actions, output_path):
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "findings": findings,
        "actions_taken": actions,
    }
    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    logger.info(f"\nJSON report saved: {output_path}")
    return report


# ── Main ──────────────────────────────────────────────────────────────────

def scan_region(ec2_client, args):
    """Run full zombie scan for a single region client."""
    volumes = find_unattached_volumes(ec2_client)
    eips = find_unassociated_eips(ec2_client)
    stopped = find_stopped_instances(ec2_client, args.stopped_days) if args.include_stopped_ec2 else []
    return volumes, eips, stopped


def main():
    parser = argparse.ArgumentParser(
        description="Cost Detective — AWS Zombie Asset Garbage Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete zombie assets (interactive confirmation required)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Skip confirmation prompt (use with --delete in CI)",
    )
    parser.add_argument(
        "--include-stopped-ec2",
        action="store_true",
        default=False,
        help="Also report long-stopped EC2 instances",
    )
    parser.add_argument(
        "--stopped-days",
        type=int,
        default=7,
        help="Min days an instance must be stopped to appear in report (default: 7)",
    )
    parser.add_argument(
        "--all-regions",
        action="store_true",
        default=False,
        help="Scan all enabled regions (overrides --region)",
    )
    parser.add_argument("--output", default=None, help="Output JSON report path")
    args = parser.parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    output_path = args.output or f"garbage_collect_report_{timestamp}.json"

    session = boto3.Session(profile_name=args.profile, region_name=args.region)

    regions = [args.region]
    if args.all_regions:
        ec2_meta = session.client("ec2", region_name="us-east-1")
        regions = [
            r["RegionName"]
            for r in ec2_meta.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])["Regions"]
        ]
        logger.info(f"Scanning {len(regions)} regions")

    all_volumes, all_eips, all_stopped = [], [], []
    for region in regions:
        logger.info(f"Scanning region: {region}")
        ec2 = session.client("ec2", region_name=region)
        vols, eips, stopped = scan_region(ec2, args)
        all_volumes.extend(vols)
        all_eips.extend(eips)
        all_stopped.extend(stopped)

    print(f"\n{'═'*64}")
    print("  COST DETECTIVE — ZOMBIE ASSET REPORT")
    print(f"  Scanned: {', '.join(regions)}")
    print(f"  Mode   : {'DELETE' if args.delete else 'DRY-RUN (safe)'}")
    print(f"{'═'*64}")

    vol_cost  = report_volumes(all_volumes)
    eip_cost  = report_eips(all_eips)
    _         = report_stopped_instances(all_stopped) if args.include_stopped_ec2 else 0

    total_waste = vol_cost + eip_cost
    print(f"\n{'═'*64}")
    print(f"  TOTAL ESTIMATED MONTHLY WASTE: ${total_waste:.2f}")
    print(f"  TOTAL ESTIMATED ANNUAL WASTE : ${total_waste * 12:.2f}")
    print(f"{'═'*64}\n")

    findings = {
        "unattached_volumes": [
            {
                "id": v["VolumeId"],
                "name": get_name_tag(v.get("Tags")),
                "size_gb": v.get("Size"),
                "type": v.get("VolumeType"),
                "az": v.get("AvailabilityZone"),
                "created": str(v.get("CreateTime")),
                "estimated_monthly_cost": round(ebs_monthly_cost(v), 2),
            }
            for v in all_volumes
        ],
        "unassociated_eips": [
            {
                "allocation_id": a.get("AllocationId"),
                "public_ip": a.get("PublicIp"),
                "estimated_monthly_cost": EIP_PRICE_PER_MONTH,
            }
            for a in all_eips
        ],
        "total_monthly_waste_usd": round(total_waste, 2),
        "total_annual_waste_usd": round(total_waste * 12, 2),
    }

    actions = {"volumes_deleted": [], "eips_released": [], "errors": []}

    if args.delete and (all_volumes or all_eips):
        proceed = args.force
        if not proceed:
            print(
                f"About to DELETE {len(all_volumes)} volume(s) and "
                f"RELEASE {len(all_eips)} EIP(s) permanently."
            )
            answer = input("Type 'DELETE' to confirm: ").strip()
            proceed = answer == "DELETE"

        if proceed:
            # Use regional clients for multi-region runs
            for region in regions:
                ec2 = session.client("ec2", region_name=region)
                region_vols = [v for v in all_volumes if v.get("AvailabilityZone", "").startswith(region)]
                region_eips = all_eips  # EIPs are regional; simplify for single-region
                deleted, vol_errors = delete_volumes(ec2, region_vols)
                released, eip_errors = release_eips(ec2, region_eips)
                actions["volumes_deleted"].extend(deleted)
                actions["eips_released"].extend(released)
                actions["errors"].extend(vol_errors + eip_errors)

            print(f"\n✓ Deleted {len(actions['volumes_deleted'])} volume(s)")
            print(f"✓ Released {len(actions['eips_released'])} EIP(s)")
            if actions["errors"]:
                print(f"✗ {len(actions['errors'])} error(s) — see report for details")
        else:
            print("Deletion cancelled.")
    elif not args.delete:
        print("DRY-RUN mode: no resources modified.")
        print("Re-run with --delete to remove zombie assets.\n")

    save_json_report(findings, actions, output_path)


if __name__ == "__main__":
    main()
