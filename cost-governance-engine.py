import json
import uuid
import os
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Attr

# =====================================================
# AWS CLIENTS
# =====================================================

ec2 = boto3.client("ec2")

dynamodb = boto3.resource("dynamodb")

lambda_client = boto3.client(
    "lambda"
)

table = dynamodb.Table(
    os.environ["TABLE_NAME"]
)

# =====================================================
# UTILITY FUNCTIONS
# =====================================================

def get_resource_name(tags):

    if not tags:
        return "N/A"

    for tag in tags:

        if tag["Key"] == "Name":
            return tag["Value"]

    return "N/A"


# =====================================================
# FINDING LOOKUPS
# =====================================================

def get_active_finding(resource_id):

    response = table.scan(
        FilterExpression=
        Attr("resource_id").eq(resource_id)
        &
        (
            Attr("status").eq("OPEN")
            |
            Attr("status").eq("APPROVED")
            |
            Attr("status").eq("REMEDIATING")
            |
            Attr("status").eq("VERIFYING")
        )
    )

    items = response.get(
        "Items",
        []
    )

    return items[0] if items else None


def get_closed_finding(resource_id):

    response = table.scan(
        FilterExpression=
        Attr("resource_id").eq(resource_id)
        &
        (
            Attr("status").eq("REMEDIATED")
            |
            Attr("status").eq("FAILED")
            |
            Attr("status").eq("REJECTED")
        )
    )

    items = response.get(
        "Items",
        []
    )

    return items[0] if items else None


# =====================================================
# FINDING MANAGEMENT
# =====================================================

def update_last_seen(
    finding_id
):

    table.update_item(
        Key={
            "finding_id":
            finding_id
        },
        UpdateExpression=
        "SET last_seen = :now",
        ExpressionAttributeValues={
            ":now":
            datetime.utcnow()
            .isoformat()
        }
    )


def save_finding(
    resource_type,
    resource_id,
    resource_name,
    finding_type,
    estimated_savings
):

    current_time = (
        datetime.utcnow()
        .isoformat()
    )

    finding = {

        "finding_id":
        str(uuid.uuid4()),

        "resource_type":
        resource_type,

        "resource_id":
        resource_id,

        "resource_name":
        resource_name,

        "finding_type":
        finding_type,

        "estimated_savings":
        str(
            estimated_savings
        ),

        "status":
        "OPEN",

        "first_seen":
        current_time,

        "last_seen":
        current_time,

        "closed_at":
        None,

        "notification_sent":
        False,

        "created_by":
        "governance-engine",

        "finding_source":
        "automated-scan"
    }

    table.put_item(
        Item=finding
    )

    return finding


def process_finding(
    resource_type,
    resource_id,
    resource_name,
    finding_type,
    estimated_savings,
    findings
):

    active = (
        get_active_finding(
            resource_id
        )
    )

    if active:

        update_last_seen(
            active[
                "finding_id"
            ]
        )

        return

    closed = (
        get_closed_finding(
            resource_id
        )
    )

    if closed:

        return

    finding = save_finding(
        resource_type,
        resource_id,
        resource_name,
        finding_type,
        estimated_savings
    )

    findings.append(
        finding
    )


# =====================================================
# ELASTIC IP ANALYZER
# =====================================================

def analyze_elastic_ips():

    findings = []

    response = (
        ec2.describe_addresses()
    )

    for address in response[
        "Addresses"
    ]:

        if (
            "AssociationId"
            not in address
        ):

            process_finding(
                resource_type=
                "ElasticIP",

                resource_id=
                address[
                    "AllocationId"
                ],

                resource_name=
                address[
                    "PublicIp"
                ],

                finding_type=
                "UNUSED",

                estimated_savings=
                3.60,

                findings=
                findings
            )

    return findings


# =====================================================
# EBS ANALYZER
# =====================================================

def analyze_ebs_volumes():

    findings = []

    response = (
        ec2.describe_volumes()
    )

    for volume in response[
        "Volumes"
    ]:

        if (
            volume["State"]
            == "available"
        ):

            process_finding(
                resource_type=
                "EBS",

                resource_id=
                volume[
                    "VolumeId"
                ],

                resource_name=
                get_resource_name(
                    volume.get(
                        "Tags",
                        []
                    )
                ),

                finding_type=
                "UNATTACHED",

                estimated_savings=
                0.08,

                findings=
                findings
            )

    return findings


# =====================================================
# EC2 ANALYZER
# =====================================================

def analyze_ec2_instances():

    findings = []

    response = (
        ec2.describe_instances()
    )

    for reservation in response[
        "Reservations"
    ]:

        for instance in reservation[
            "Instances"
        ]:

            state = instance[
                "State"
            ][
                "Name"
            ]

            if state == "stopped":

                process_finding(
                    resource_type=
                    "EC2",

                    resource_id=
                    instance[
                        "InstanceId"
                    ],

                    resource_name=
                    get_resource_name(
                        instance.get(
                            "Tags",
                            []
                        )
                    ),

                    finding_type=
                    "STOPPED_INSTANCE",

                    estimated_savings=
                    8.50,

                    findings=
                    findings
                )

    return findings


# =====================================================
# SLACK TRIGGER
# =====================================================

def trigger_slack_notifications():

    try:

        lambda_client.invoke(

            FunctionName=
            os.environ[
                "SLACK_LAMBDA_NAME"
            ],

            InvocationType=
            "Event"
        )

        print(
            "Slack notification "
            "engine triggered."
        )

    except Exception as e:

        print(
            f"Slack trigger failed: "
            f"{str(e)}"
        )


# =====================================================
# SUMMARY
# =====================================================

def calculate_total_savings():

    response = table.scan()

    total = 0

    for item in response.get(
        "Items",
        []
    ):

        if item["status"] in [

            "OPEN",

            "APPROVED",

            "REMEDIATING",

            "VERIFYING"
        ]:

            total += float(
                item[
                    "estimated_savings"
                ]
            )

    return round(
        total,
        2
    )


# =====================================================
# MAIN
# =====================================================

def lambda_handler(
    event,
    context
):

    eip_findings = (
        analyze_elastic_ips()
    )

    ebs_findings = (
        analyze_ebs_volumes()
    )

    ec2_findings = (
        analyze_ec2_instances()
    )

    total_new_findings = (

        len(eip_findings)

        +

        len(ebs_findings)

        +

        len(ec2_findings)
    )

    if total_new_findings > 0:

        trigger_slack_notifications()

    total_savings = (
        calculate_total_savings()
    )

    return {

        "statusCode": 200,

        "body": json.dumps(

            {

                "message":
                "Governance Scan Completed",

                "elastic_ip_findings":
                len(eip_findings),

                "ebs_findings":
                len(ebs_findings),

                "ec2_findings":
                len(ec2_findings),

                "new_findings":
                total_new_findings,

                "potential_monthly_savings":
                total_savings
            }
        )
    }