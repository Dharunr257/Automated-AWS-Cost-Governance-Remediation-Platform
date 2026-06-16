import json
import os
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

# =====================================================
# AWS CLIENTS
# =====================================================

ec2 = boto3.client("ec2")

dynamodb = boto3.resource("dynamodb")

sns = boto3.client("sns")

table = dynamodb.Table(
    os.environ["TABLE_NAME"]
)

SNS_TOPIC_ARN = os.environ[
    "SNS_TOPIC_ARN"
]

# =====================================================
# STATUS HELPERS
# =====================================================

def update_status(
    finding_id,
    status
):

    table.update_item(
        Key={
            "finding_id": finding_id
        },
        UpdateExpression=
        "SET #s = :status",
        ExpressionAttributeNames={
            "#s": "status"
        },
        ExpressionAttributeValues={
            ":status": status
        }
    )


def mark_remediated(
    finding_id
):

    timestamp = (
        datetime.utcnow()
        .isoformat()
    )

    table.update_item(
        Key={
            "finding_id": finding_id
        },
        UpdateExpression=
        """
        SET #s = :status,
            remediated_at = :time,
            closed_at = :time
        """,
        ExpressionAttributeNames={
            "#s": "status"
        },
        ExpressionAttributeValues={
            ":status":
            "REMEDIATED",

            ":time":
            timestamp
        }
    )


def mark_failed(
    finding_id
):

    table.update_item(
        Key={
            "finding_id": finding_id
        },
        UpdateExpression=
        "SET #s = :status",
        ExpressionAttributeNames={
            "#s": "status"
        },
        ExpressionAttributeValues={
            ":status":
            "FAILED"
        }
    )


# =====================================================
# SNS NOTIFICATIONS
# =====================================================

def send_remediation_notification(
    finding
):

    message = f"""
AWS Cost Governance Remediation Report

==================================================

Finding ID :
{finding.get('finding_id', 'N/A')}
Finding Type :
{finding.get('finding_type', 'N/A')}
Resource Type :
{finding.get('resource_type', 'N/A')}
Resource Name :
{finding.get('resource_name', 'N/A')}
Resource ID :
{finding.get('resource_id', 'N/A')}

Status :
REMEDIATED

Estimated Monthly Savings :
${finding.get('estimated_savings', 0)}/month

First Seen :
{finding.get('first_seen', 'N/A')}
Last Seen :
{finding.get('last_seen', 'N/A')}

==================================================

AWS Cost Governance Platform
Automated Remediation Completed Successfully
"""

    sns.publish(
        TopicArn=
        SNS_TOPIC_ARN,

        Subject=
        f"[REMEDIATED] {finding.get('resource_type','Resource')} - {finding.get('resource_name','Unknown')}",

        Message=
        message
    )
# =====================================================
# FINDINGS
# =====================================================

def get_approved_findings():

    response = table.scan(
        FilterExpression=
        Attr("status").eq(
            "APPROVED"
        )
    )

    return response.get(
        "Items",
        []
    )


def get_verifying_findings():

    response = table.scan(
        FilterExpression=
        Attr("status").eq(
            "VERIFYING"
        )
    )

    return response.get(
        "Items",
        []
    )


# =====================================================
# VERIFICATION FUNCTIONS
# =====================================================

def verify_eip(
    allocation_id
):

    response = (
        ec2.describe_addresses()
    )

    for address in response[
        "Addresses"
    ]:

        if address.get(
            "AllocationId"
        ) == allocation_id:

            return False

    return True


def verify_volume(
    volume_id
):

    try:

        ec2.describe_volumes(
            VolumeIds=[
                volume_id
            ]
        )

        return False

    except ClientError as e:

        if (
            "InvalidVolume.NotFound"
            in str(e)
        ):
            return True

        raise


def verify_instance(
    instance_id
):

    try:

        response = (
            ec2.describe_instances(
                InstanceIds=[
                    instance_id
                ]
            )
        )

        for reservation in response[
            "Reservations"
        ]:

            for instance in reservation[
                "Instances"
            ]:

                state = instance[
                    "State"
                ]["Name"]

                if state in [
                    "terminated",
                    "shutting-down"
                ]:
                    return True

        return False

    except ClientError:

        return True


# =====================================================
# REMEDIATION ACTIONS
# =====================================================

def remediate_eip(
    finding
):

    ec2.release_address(
        AllocationId=
        finding[
            "resource_id"
        ]
    )


def remediate_ebs(
    finding
):

    ec2.delete_volume(
        VolumeId=
        finding[
            "resource_id"
        ]
    )


def remediate_ec2(
    finding
):

    ec2.terminate_instances(
        InstanceIds=[
            finding[
                "resource_id"
            ]
        ]
    )


# =====================================================
# APPROVED -> VERIFYING
# =====================================================

def process_approved_finding(
    finding
):

    finding_id = (
        finding["finding_id"]
    )

    resource_type = (
        finding["resource_type"]
    )

    try:

        update_status(
            finding_id,
            "REMEDIATING"
        )

        if (
            resource_type
            == "ElasticIP"
        ):

            remediate_eip(
                finding
            )

        elif (
            resource_type
            == "EBS"
        ):

            remediate_ebs(
                finding
            )

        elif (
            resource_type
            == "EC2"
        ):

            remediate_ec2(
                finding
            )

        update_status(
            finding_id,
            "VERIFYING"
        )

        return {
            "resource":
            finding[
                "resource_id"
            ],

            "type":
            resource_type,

            "status":
            "VERIFYING"
        }

    except Exception as e:

        mark_failed(
            finding_id
        )

        return {
            "resource":
            finding[
                "resource_id"
            ],

            "type":
            resource_type,

            "status":
            "FAILED",

            "error":
            str(e)
        }


# =====================================================
# VERIFYING -> REMEDIATED
# =====================================================

def process_verifying_finding(
    finding
):

    finding_id = (
        finding["finding_id"]
    )

    resource_type = (
        finding["resource_type"]
    )

    resource_id = (
        finding["resource_id"]
    )

    verified = False

    if (
        resource_type
        == "ElasticIP"
    ):

        verified = verify_eip(
            resource_id
        )

    elif (
        resource_type
        == "EBS"
    ):

        verified = verify_volume(
            resource_id
        )

    elif (
        resource_type
        == "EC2"
    ):

        verified = verify_instance(
            resource_id
        )

    if verified:

        mark_remediated(
            finding_id
        )

        send_remediation_notification(
            finding
        )

        return {
            "resource":
            resource_id,

            "type":
            resource_type,

            "status":
            "REMEDIATED"
        }

    return {
        "resource":
        resource_id,

        "type":
        resource_type,

        "status":
        "VERIFYING"
    }


# =====================================================
# MAIN
# =====================================================

def lambda_handler(
    event,
    context
):

    results = []

    approved = (
        get_approved_findings()
    )

    for finding in approved:

        results.append(
            process_approved_finding(
                finding
            )
        )

    verifying = (
        get_verifying_findings()
    )

    for finding in verifying:

        results.append(
            process_verifying_finding(
                finding
            )
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "approved":
                len(approved),

                "verifying":
                len(verifying),

                "results":
                results
            }
        )
    }