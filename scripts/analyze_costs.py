#!/usr/bin/env python3
"""
Cost Detective - Cost Explorer Analysis Script
==============================================
Queries AWS Cost Explorer for a detailed breakdown of your spending,
identifies top cost drivers, and flags untagged resources.

Produces:
  - Console table with spend by service (last 30 days)
  - Spend trend (daily) for the top 5 services
  - Untagged resource summary (EC2, EBS, S3)
  - JSON report for further processing

Usage:
  python analyze_costs.py
  python analyze_costs.py --days 90 --profile myprofile
  python analyze_costs.py --days 30 --output cost_report.json

Prerequisites:
  - AWS Cost Explorer must be enabled (Settings → Cost Explorer → Enable)
  - IAM permission: ce:GetCostAndUsage, ce:GetCostForecast, ec2:Describe*
"""

import boto3
import argparse
import json
import logging
from datetime import date, timedelta, datetime
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

REQUIRED_TAGS = ["CostCenter", "Environment", "Project", "Owner"]


# ── Cost Explorer helpers ──────────────────────────────────────────────────

def get_cost_by_service(ce_client, start: str, end: str) -> list[dict]:
    """Return spend grouped by AWS service, sorted by cost descending."""
    resp = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    results = []
    for group in resp["ResultsByTime"][0]["Groups"]:
        service = group["Keys"][0]
        amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
        results.append({"service": service, "cost": round(amount, 4)})
    return sorted(results, key=lambda x: x["cost"], reverse=True)


def get_daily_trend(ce_client, start: str, end: str, top_services: list[str]) -> list[dict]:
    """Return daily spend for the top N services."""
    service_filter = {
        "Dimensions": {
            "Key": "SERVICE",
            "Values": top_services,
            "MatchOptions": ["EQUALS"],
        }
    }
    resp = ce_client.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Filter=service_filter,
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    rows = []
    for period in resp["ResultsByTime"]:
        date_str = period["TimePeriod"]["Start"]
        for group in period["Groups"]:
            rows.append({
                "date": date_str,
                "service": group["Keys"][0],
                "cost": round(float(group["Metrics"]["UnblendedCost"]["Amount"]), 4),
            })
    return rows


def get_cost_forecast(ce_client) -> dict | None:
    """Return month-to-date forecast. May fail if not enough data."""
    try:
        today = date.today()
        month_end = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        if today.strftime("%Y-%m-%d") >= month_end.strftime("%Y-%m-%d"):
            return None
        resp = ce_client.get_cost_forecast(
            TimePeriod={
                "Start": today.strftime("%Y-%m-%d"),
                "End": month_end.strftime("%Y-%m-%d"),
            },
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
        )
        return {
            "mean": round(float(resp["Total"]["Amount"]), 2),
            "lower_bound": round(float(resp["ForecastResultsByTime"][0]["PredictionIntervalLowerBound"]["Amount"]), 2),
            "upper_bound": round(float(resp["ForecastResultsByTime"][0]["PredictionIntervalUpperBound"]["Amount"]), 2),
        }
    except ClientError as e:
        logger.warning(f"Could not fetch forecast: {e.response['Error']['Message']}")
        return None


def get_untagged_instances(ec2_client) -> list[dict]:
    """Find EC2 instances missing any required tag."""
    paginator = ec2_client.get_paginator("describe_instances")
    missing = []
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}]
    ):
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                missing_tags = [t for t in REQUIRED_TAGS if t not in tags]
                if missing_tags:
                    missing.append({
                        "id": inst["InstanceId"],
                        "type": inst.get("InstanceType"),
                        "state": inst["State"]["Name"],
                        "name": tags.get("Name", "(unnamed)"),
                        "missing_tags": missing_tags,
                    })
    return missing


def get_untagged_volumes(ec2_client) -> list[dict]:
    """Find EBS volumes missing required tags."""
    paginator = ec2_client.get_paginator("describe_volumes")
    missing = []
    for page in paginator.paginate():
        for vol in page["Volumes"]:
            tags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
            missing_tags = [t for t in REQUIRED_TAGS if t not in tags]
            if missing_tags:
                missing.append({
                    "id": vol["VolumeId"],
                    "size_gb": vol.get("Size"),
                    "type": vol.get("VolumeType"),
                    "state": vol.get("State"),
                    "missing_tags": missing_tags,
                })
    return missing


# ── Formatters ─────────────────────────────────────────────────────────────

def print_service_table(services: list[dict], total: float):
    print(f"\n{'━'*64}")
    print(f"  SPEND BY SERVICE (last analysis period)")
    print(f"{'━'*64}")
    print(f"  {'Service':<42} {'Cost':>10}  {'% Total':>7}")
    print(f"  {'─'*42} {'─'*10}  {'─'*7}")
    for svc in services[:20]:
        pct = (svc["cost"] / total * 100) if total > 0 else 0
        bar_len = int(pct / 2)
        bar = "█" * bar_len
        print(f"  {svc['service']:<42} ${svc['cost']:>9.2f}  {pct:>6.1f}%  {bar}")
    print(f"  {'─'*42} {'─'*10}")
    print(f"  {'TOTAL':<42} ${total:>9.2f}")


def print_forecast(forecast: dict | None):
    print(f"\n{'━'*64}")
    print(f"  MONTH-END FORECAST")
    print(f"{'━'*64}")
    if forecast:
        print(f"  Projected spend : ${forecast['mean']:.2f}")
        print(f"  Range           : ${forecast['lower_bound']:.2f} – ${forecast['upper_bound']:.2f}")
        if forecast["mean"] > 50:
            print(f"  ⚠  Forecast EXCEEDS $50 budget threshold!")
        else:
            print(f"  ✓  Forecast within $50 budget threshold")
    else:
        print("  Forecast not available (insufficient data or end of month).")


def print_untagged(instances: list[dict], volumes: list[dict]):
    print(f"\n{'━'*64}")
    print(f"  UNTAGGED RESOURCES (missing: {', '.join(REQUIRED_TAGS)})")
    print(f"{'━'*64}")
    print(f"\n  EC2 Instances without required tags: {len(instances)}")
    for inst in instances[:10]:
        print(
            f"    {inst['id']}  {inst['name']:<20}  state:{inst['state']:<10}"
            f"  missing: {', '.join(inst['missing_tags'])}"
        )
    if len(instances) > 10:
        print(f"    ... and {len(instances) - 10} more")

    print(f"\n  EBS Volumes without required tags: {len(volumes)}")
    for vol in volumes[:10]:
        print(
            f"    {vol['id']}  {vol['size_gb']} GB {vol['type']:<6}"
            f"  state:{vol['state']:<10}  missing: {', '.join(vol['missing_tags'])}"
        )
    if len(volumes) > 10:
        print(f"    ... and {len(volumes) - 10} more")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cost Detective — AWS Cost Analyzer")
    parser.add_argument("--days", type=int, default=30, help="Look-back period in days (default: 30)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    output_path = args.output or f"cost_analysis_{timestamp}.json"

    session = boto3.Session(profile_name=args.profile, region_name=args.region)

    # Cost Explorer is a global service, always in us-east-1
    ce = session.client("ce", region_name="us-east-1")
    ec2 = session.client("ec2", region_name=args.region)

    print(f"\n{'═'*64}")
    print("  COST DETECTIVE — AWS Cost Analysis")
    print(f"  Period : {start_str} → {end_str} ({args.days} days)")
    print(f"  Region : {args.region}")
    print(f"{'═'*64}")

    logger.info("Fetching cost breakdown from Cost Explorer...")
    try:
        services = get_cost_by_service(ce, start_str, end_str)
    except ClientError as e:
        logger.error(f"Cost Explorer query failed: {e}")
        logger.error("Ensure Cost Explorer is enabled and IAM has ce:GetCostAndUsage permission.")
        services = []

    total = sum(s["cost"] for s in services)
    print_service_table(services, total)

    logger.info("Fetching month-end cost forecast...")
    forecast = get_cost_forecast(ce)
    print_forecast(forecast)

    logger.info("Checking for untagged resources...")
    try:
        untagged_instances = get_untagged_instances(ec2)
        untagged_volumes = get_untagged_volumes(ec2)
    except ClientError as e:
        logger.warning(f"Could not scan for untagged resources: {e}")
        untagged_instances, untagged_volumes = [], []

    print_untagged(untagged_instances, untagged_volumes)

    # Top 5 services for trend
    top_services = [s["service"] for s in services[:5] if s["cost"] > 0]
    daily_trend = []
    if top_services:
        logger.info("Fetching daily cost trend...")
        try:
            daily_trend = get_daily_trend(ce, start_str, end_str, top_services)
        except ClientError as e:
            logger.warning(f"Could not fetch daily trend: {e}")

    # Cost anomaly highlights
    anomalies = [s for s in services if s["cost"] > total * 0.40]

    print(f"\n{'━'*64}")
    print("  COST ANOMALY HIGHLIGHTS")
    print(f"{'━'*64}")
    if anomalies:
        for a in anomalies:
            pct = a["cost"] / total * 100 if total else 0
            print(f"  ⚠  {a['service']} accounts for {pct:.0f}% of total spend (${a['cost']:.2f})")
    else:
        print("  No single service dominates (>40% of spend). Spend is distributed.")

    # Savings recommendations
    print(f"\n{'━'*64}")
    print("  QUICK-WIN RECOMMENDATIONS")
    print(f"{'━'*64}")
    if untagged_instances:
        print(f"  1. Tag {len(untagged_instances)} EC2 instance(s) — required for chargeback")
    if untagged_volumes:
        print(f"  2. Tag {len(untagged_volumes)} EBS volume(s) — missing cost allocation tags")
    ec2_spend = next((s["cost"] for s in services if "EC2" in s["service"]), 0)
    if ec2_spend > 20:
        savings = ec2_spend * 0.60
        print(f"  3. Migrate eligible EC2 workloads to Spot → save ~${savings:.0f}/month")
    print(f"  4. Review Savings Plans / Reserved Instances if EC2 baseline is consistent")
    print(f"  5. Enable S3 Intelligent-Tiering for infrequently accessed data")

    print()

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "period": {"start": start_str, "end": end_str, "days": args.days},
        "total_spend_usd": round(total, 2),
        "forecast": forecast,
        "services": services,
        "daily_trend": daily_trend,
        "compliance": {
            "untagged_instances": untagged_instances,
            "untagged_volumes": untagged_volumes,
        },
        "required_tags": REQUIRED_TAGS,
    }

    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    logger.info(f"Report saved: {output_path}")


if __name__ == "__main__":
    main()
