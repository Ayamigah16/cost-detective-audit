#!/usr/bin/env python3
"""
Cost Detective - Sandbox Resource Creator
==========================================
Creates intentionally "wasteful" resources in a sandbox environment
to demonstrate zombie asset detection. Resources created:

  - 3x unattached EBS volumes (gp3, varied sizes)
  - 2x unassociated Elastic IP addresses
  - 1x idle large EC2 instance (m5.large) — optional, tagged as zombie

WARNING: These resources WILL incur AWS charges. Run garbage_collect.py
         to clean them up immediately after demonstrating the audit.

Usage:
  python setup_sandbox.py --region us-east-1
  python setup_sandbox.py --region us-east-1 --no-ec2   # Skip EC2, EBS/EIP only
  python setup_sandbox.py --region us-east-1 --cleanup  # Destroy resources created by a prior run
"""

import boto3
import argparse
import json
import logging
import sys
import time
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SANDBOX_TAG = {"Key": "Environment", "Value": "CostDetectiveSandbox"}
COST_CENTER_TAG_MISSING = True  # Intentionally omit CostCenter for compliance demo

STATE_FILE = "sandbox_state.json"


# ---------------------------------------------------------------------------
# Resource creators
# ---------------------------------------------------------------------------

def create_ebs_volumes(ec2, region):
    """Create 3 unattached EBS volumes in the first available AZ."""
    azs = ec2.describe_availability_zones(
        Filters=[{"Name": "state", "Values": ["available"]}]
    )["AvailabilityZones"]
    az = azs[0]["ZoneName"]

    configs = [
        {"size": 20, "type": "gp3", "name": "zombie-vol-01"},
        {"size": 50, "type": "gp2", "name": "zombie-vol-02"},
        {"size": 100, "type": "gp3", "name": "zombie-vol-03"},
    ]

    volume_ids = []
    for cfg in configs:
        vol = ec2.create_volume(
            AvailabilityZone=az,
            Size=cfg["size"],
            VolumeType=cfg["type"],
            TagSpecifications=[
                {
                    "ResourceType": "volume",
                    "Tags": [
                        SANDBOX_TAG,
                        {"Key": "Name", "Value": cfg["name"]},
                        {"Key": "Purpose", "Value": "zombie-demo"},
                    ],
                }
            ],
        )
        volume_ids.append(vol["VolumeId"])
        logger.info(
            f"Created EBS volume: {vol['VolumeId']} ({cfg['size']} GB {cfg['type']}) in {az}"
        )
    return volume_ids


def create_elastic_ips(ec2):
    """Create 2 unassociated Elastic IPs."""
    eip_ids = []
    for i in range(2):
        addr = ec2.allocate_address(
            Domain="vpc",
            TagSpecifications=[
                {
                    "ResourceType": "elastic-ip",
                    "Tags": [
                        SANDBOX_TAG,
                        {"Key": "Name", "Value": f"zombie-eip-0{i+1}"},
                        {"Key": "Purpose", "Value": "zombie-demo"},
                    ],
                }
            ],
        )
        eip_ids.append(addr["AllocationId"])
        logger.info(
            f"Allocated EIP: {addr['PublicIp']} (AllocationId: {addr['AllocationId']})"
        )
    return eip_ids


def get_latest_amazon_linux_ami(ec2):
    """Return the latest Amazon Linux 2023 AMI ID."""
    response = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-*-x86_64"]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
        ],
    )
    images = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
    if not images:
        raise RuntimeError("No Amazon Linux 2023 AMI found")
    return images[0]["ImageId"]


def create_idle_ec2(ec2, region):
    """Launch an oversized m5.large EC2 instance with no meaningful workload."""
    ami_id = get_latest_amazon_linux_ami(ec2)
    logger.info(f"Using AMI: {ami_id}")

    # Deliberately omit 'CostCenter' tag to trigger compliance findings
    response = ec2.run_instances(
        ImageId=ami_id,
        InstanceType="m5.large",
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    SANDBOX_TAG,
                    {"Key": "Name", "Value": "zombie-idle-instance"},
                    {"Key": "Purpose", "Value": "zombie-demo"},
                    # NOTE: CostCenter intentionally absent
                ],
            }
        ],
    )
    instance_id = response["Instances"][0]["InstanceId"]
    logger.info(f"Launched EC2 instance: {instance_id} (m5.large) — waiting for running state")

    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])
    logger.info(f"Instance {instance_id} is now running")
    return instance_id


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_sandbox(ec2, state):
    """Delete all resources created by this script."""
    errors = []

    for vol_id in state.get("volume_ids", []):
        try:
            ec2.delete_volume(VolumeId=vol_id)
            logger.info(f"Deleted volume: {vol_id}")
        except ClientError as e:
            logger.error(f"Failed to delete {vol_id}: {e}")
            errors.append(vol_id)

    for alloc_id in state.get("eip_allocation_ids", []):
        try:
            ec2.release_address(AllocationId=alloc_id)
            logger.info(f"Released EIP: {alloc_id}")
        except ClientError as e:
            logger.error(f"Failed to release {alloc_id}: {e}")
            errors.append(alloc_id)

    for instance_id in state.get("instance_ids", []):
        try:
            ec2.terminate_instances(InstanceIds=[instance_id])
            logger.info(f"Terminated instance: {instance_id}")
            waiter = ec2.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=[instance_id])
            logger.info(f"Instance {instance_id} terminated")
        except ClientError as e:
            logger.error(f"Failed to terminate {instance_id}: {e}")
            errors.append(instance_id)

    if errors:
        logger.warning(f"Some resources could not be cleaned up: {errors}")
    else:
        logger.info("Sandbox cleanup complete — all resources removed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cost Detective Sandbox Setup")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--profile", default=None, help="AWS CLI profile")
    parser.add_argument("--no-ec2", action="store_true", help="Skip EC2 instance (EBS+EIP only)")
    parser.add_argument("--cleanup", action="store_true", help="Destroy sandbox resources from prior run")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ec2 = session.client("ec2")

    if args.cleanup:
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            cleanup_sandbox(ec2, state)
        except FileNotFoundError:
            logger.error(f"State file '{STATE_FILE}' not found. Nothing to clean up.")
            sys.exit(1)
        return

    logger.info("=" * 60)
    logger.info("Cost Detective - Creating sandbox zombie resources")
    logger.info(f"Region: {args.region}")
    logger.info("=" * 60)

    state = {
        "region": args.region,
        "volume_ids": [],
        "eip_allocation_ids": [],
        "instance_ids": [],
    }

    try:
        state["volume_ids"] = create_ebs_volumes(ec2, args.region)
        state["eip_allocation_ids"] = create_elastic_ips(ec2)

        if not args.no_ec2:
            instance_id = create_idle_ec2(ec2, args.region)
            state["instance_ids"].append(instance_id)

    except Exception as e:
        logger.error(f"Error during setup: {e}")
        logger.info("Saving partial state — run with --cleanup to remove created resources")
    finally:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"State saved to: {STATE_FILE}")

    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY — Zombie Resources Created:")
    logger.info(f"  EBS Volumes    : {state['volume_ids']}")
    logger.info(f"  Elastic IPs    : {state['eip_allocation_ids']}")
    logger.info(f"  EC2 Instances  : {state['instance_ids']}")
    logger.info("=" * 60)
    logger.info("Run garbage_collect.py to detect and clean up these resources.")


if __name__ == "__main__":
    main()
