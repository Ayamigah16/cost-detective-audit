#!/usr/bin/env python3
"""
Cost Detective - Tag Compliance Checker
=======================================
Audits EC2 instances, EBS volumes, and related resources for
adherence to the organisation's mandatory tagging policy.

Required tags (configurable via REQUIRED_TAGS):
  - CostCenter   : billing chargeback unit  (e.g. "ENG-001")
  - Environment  : workload tier            (e.g. "prod" | "staging" | "dev")
  - Project      : owning project / product (e.g. "platform")
  - Owner        : team or individual email (e.g. "platform@company.com")

Exit codes:
  0  All resources compliant
  1  Non-compliant resources found
  2  Script error

Usage:
  python tag_compliance_check.py
  python tag_compliance_check.py --region us-west-2 --strict
  python tag_compliance_check.py --output report.json
  python tag_compliance_check.py --fix-dryrun   # Show what auto-tagging would do
"""

import boto3
import argparse
import json
import sys
import logging
from datetime import datetime
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

REQUIRED_TAGS = ["CostCenter", "Environment", "Project", "Owner"]
VALID_ENVIRONMENTS = {"prod", "production", "staging", "stage", "dev", "development", "test", "sandbox"}


# ── Scanners ──────────────────────────────────────────────────────────────

def check_tags(resource_id: str, resource_type: str, tags: list[dict]) -> dict:
    """Evaluate a resource's tags against policy."""
    tag_map = {t["Key"]: t["Value"] for t in (tags or [])}
    missing = [k for k in REQUIRED_TAGS if k not in tag_map]
    invalid = []

    if "Environment" in tag_map:
        if tag_map["Environment"].lower() not in VALID_ENVIRONMENTS:
            invalid.append(
                f"Environment='{tag_map['Environment']}' not in {sorted(VALID_ENVIRONMENTS)}"
            )

    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "tags_present": tag_map,
        "missing_tags": missing,
        "invalid_tags": invalid,
        "compliant": len(missing) == 0 and len(invalid) == 0,
    }


def scan_ec2_instances(ec2) -> list[dict]:
    results = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                if inst["State"]["Name"] == "terminated":
                    continue
                result = check_tags(
                    inst["InstanceId"], "EC2::Instance", inst.get("Tags", [])
                )
                result["extra"] = {
                    "instance_type": inst.get("InstanceType"),
                    "state": inst["State"]["Name"],
                    "launch_time": str(inst.get("LaunchTime")),
                }
                results.append(result)
    return results


def scan_ebs_volumes(ec2) -> list[dict]:
    results = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate():
        for vol in page["Volumes"]:
            result = check_tags(vol["VolumeId"], "EC2::Volume", vol.get("Tags", []))
            result["extra"] = {
                "size_gb": vol.get("Size"),
                "volume_type": vol.get("VolumeType"),
                "state": vol.get("State"),
                "attached_to": [
                    a["InstanceId"] for a in vol.get("Attachments", [])
                ],
            }
            results.append(result)
    return results


def scan_elastic_ips(ec2) -> list[dict]:
    results = []
    resp = ec2.describe_addresses()
    for addr in resp["Addresses"]:
        result = check_tags(
            addr.get("AllocationId", addr.get("PublicIp")),
            "EC2::ElasticIP",
            addr.get("Tags", []),
        )
        result["extra"] = {
            "public_ip": addr.get("PublicIp"),
            "associated": "AssociationId" in addr,
        }
        results.append(result)
    return results


def scan_security_groups(ec2) -> list[dict]:
    results = []
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page["SecurityGroups"]:
            if sg["GroupName"] == "default":
                continue
            result = check_tags(sg["GroupId"], "EC2::SecurityGroup", sg.get("Tags", []))
            result["extra"] = {"name": sg["GroupName"], "vpc_id": sg.get("VpcId")}
            results.append(result)
    return results


# ── Reporter ──────────────────────────────────────────────────────────────

def print_compliance_report(all_results: list[dict]) -> tuple[int, int]:
    compliant = [r for r in all_results if r["compliant"]]
    non_compliant = [r for r in all_results if not r["compliant"]]

    total = len(all_results)
    pct = (len(compliant) / total * 100) if total else 100

    print(f"\n{'═'*68}")
    print(f"  COST DETECTIVE — TAG COMPLIANCE REPORT")
    print(f"{'═'*68}")
    print(f"  Total resources scanned : {total}")
    print(f"  Compliant               : {len(compliant)}")
    print(f"  Non-compliant           : {len(non_compliant)}")
    print(f"  Compliance rate         : {pct:.1f}%")

    if pct == 100:
        print(f"\n  ✓ All resources are fully compliant with the tagging policy.")
        return len(compliant), 0

    print(f"\n{'━'*68}")
    print("  NON-COMPLIANT RESOURCES")
    print(f"{'━'*68}")

    for r in non_compliant:
        print(f"\n  {r['resource_type']:<22} {r['resource_id']}")
        if r["missing_tags"]:
            print(f"    Missing tags : {', '.join(r['missing_tags'])}")
        if r["invalid_tags"]:
            print(f"    Invalid      : {'; '.join(r['invalid_tags'])}")
        if r.get("extra"):
            extras = r["extra"]
            if "instance_type" in extras:
                print(f"    Instance     : {extras.get('instance_type')} | state: {extras.get('state')}")
            elif "size_gb" in extras:
                print(f"    Volume       : {extras.get('size_gb')} GB {extras.get('volume_type')} | state: {extras.get('state')}")
            elif "public_ip" in extras:
                print(f"    EIP          : {extras.get('public_ip')} | associated: {extras.get('associated')}")

    # Breakdown by missing tag
    print(f"\n{'━'*68}")
    print("  MISSING TAG FREQUENCY")
    print(f"{'━'*68}")
    from collections import Counter
    tag_freq: Counter = Counter()
    for r in non_compliant:
        tag_freq.update(r["missing_tags"])
    for tag, count in tag_freq.most_common():
        bar = "█" * count
        print(f"  {tag:<15} {count:>4} resources  {bar}")

    return len(compliant), len(non_compliant)


# ── Auto-fix dry-run ──────────────────────────────────────────────────────

def show_autofix_plan(non_compliant: list[dict]):
    """Print what a tag remediation script would do."""
    print(f"\n{'━'*68}")
    print("  AUTO-TAG DRY-RUN (proposed remediation)")
    print(f"{'━'*68}")
    print("  The following tags would be applied with placeholder values:\n")
    for r in non_compliant[:20]:
        tags_to_apply = {
            k: f"REPLACE_ME_{k.upper()}"
            for k in r["missing_tags"]
        }
        print(f"  aws ec2 create-tags \\")
        print(f"    --resources {r['resource_id']} \\")
        tag_str = " ".join(f"Key={k},Value={v}" for k, v in tags_to_apply.items())
        print(f"    --tags {tag_str}\n")
    if len(non_compliant) > 20:
        print(f"  ... and {len(non_compliant) - 20} more resources")
    print("  Replace REPLACE_ME_* values with actual values before running.")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cost Detective — Tag Compliance Checker")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit code 1 if ANY resource is non-compliant (useful in CI)",
    )
    parser.add_argument("--fix-dryrun", action="store_true", help="Show auto-tag CLI commands")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    output_path = args.output or f"tag_compliance_{timestamp}.json"

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ec2 = session.client("ec2", region_name=args.region)

    logger.info(f"Starting tag compliance scan | Region: {args.region}")
    logger.info(f"Required tags: {REQUIRED_TAGS}")

    try:
        all_results = []
        logger.info("Scanning EC2 instances...")
        all_results.extend(scan_ec2_instances(ec2))
        logger.info("Scanning EBS volumes...")
        all_results.extend(scan_ebs_volumes(ec2))
        logger.info("Scanning Elastic IPs...")
        all_results.extend(scan_elastic_ips(ec2))
        logger.info("Scanning Security Groups...")
        all_results.extend(scan_security_groups(ec2))
    except ClientError as e:
        logger.error(f"AWS API error: {e}")
        sys.exit(2)

    n_compliant, n_non_compliant = print_compliance_report(all_results)

    non_compliant_list = [r for r in all_results if not r["compliant"]]
    if args.fix_dryrun and non_compliant_list:
        show_autofix_plan(non_compliant_list)

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "region": args.region,
        "required_tags": REQUIRED_TAGS,
        "summary": {
            "total": len(all_results),
            "compliant": n_compliant,
            "non_compliant": n_non_compliant,
            "compliance_pct": round(n_compliant / len(all_results) * 100, 1) if all_results else 100,
        },
        "resources": all_results,
    }

    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    logger.info(f"Report saved: {output_path}")

    if args.strict and n_non_compliant > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
