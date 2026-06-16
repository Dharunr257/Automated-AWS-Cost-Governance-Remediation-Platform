import json
import os

import boto3
import urllib3

from boto3.dynamodb.conditions import (
    Attr
)

# =====================================================
# AWS CLIENTS
# =====================================================

dynamodb = boto3.resource(
    "dynamodb"
)

table = dynamodb.Table(
    os.environ["TABLE_NAME"]
)

SLACK_WEBHOOK_URL = os.environ[
    "SLACK_WEBHOOK_URL"
]

http = urllib3.PoolManager()

# =====================================================
# GET UNSENT FINDINGS
# =====================================================

def get_pending_notifications():

    response = table.scan(

        FilterExpression=

        Attr("status").eq("OPEN")

        &

        Attr(
            "notification_sent"
        ).eq(False)
    )

    return response.get(
        "Items",
        []
    )

# =====================================================
# MARK SENT
# =====================================================

def mark_notification_sent(
    finding_id
):

    table.update_item(

        Key={
            "finding_id":
            finding_id
        },

        UpdateExpression=
        """
        SET notification_sent = :sent
        """,

        ExpressionAttributeValues={
            ":sent": True
        }
    )

# =====================================================
# SEND TO SLACK
# =====================================================

def send_to_slack(
    finding
):

    payload = {

        "blocks": [

            {
                "type": "header",

                "text": {
                    "type":
                    "plain_text",

                    "text":
                    "🚨 AWS Cost Governance Finding"
                }
            },

            {
                "type": "section",

                "text": {
                    "type":
                    "mrkdwn",

                    "text":

                    (
                        f"*Finding ID:*\n"
                        f"`{finding.get('finding_id','N/A')}`\n\n"

                        f"*Finding Type:*\n"
                        f"{finding.get('finding_type','N/A')}\n\n"

                        f"*Resource Type:*\n"
                        f"{finding.get('resource_type','N/A')}\n\n"

                        f"*Resource Name:*\n"
                        f"{finding.get('resource_name','N/A')}\n\n"

                        f"*Resource ID:*\n"
                        f"`{finding.get('resource_id','N/A')}`\n\n"

                        f"*Potential Monthly Savings:*\n"
                        f"${finding.get('estimated_savings',0)}/month\n\n"

                        f"*Detected At:*\n"
                        f"{finding.get('first_seen','N/A')}\n\n"

                        f"*Current Status:*\n"
                        f"{finding.get('status','OPEN')}"
                    )
                }
            },

            {
                "type":
                "actions",

                "elements": [

                    {
                        "type":
                        "button",

                        "text": {
                            "type":
                            "plain_text",

                            "text":
                            "✅ Approve"
                        },

                        "style":
                        "primary",

                        "action_id":
                        "approve",

                        "value":
                        finding[
                            "finding_id"
                        ]
                    },

                    {
                        "type":
                        "button",

                        "text": {
                            "type":
                            "plain_text",

                            "text":
                            "❌ Reject"
                        },

                        "style":
                        "danger",

                        "action_id":
                        "reject",

                        "value":
                        finding[
                            "finding_id"
                        ]
                    }
                ]
            }
        ]
    }

    response = http.request(

        "POST",

        SLACK_WEBHOOK_URL,

        body=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),

        headers={
            "Content-Type":
            "application/json"
        }
    )

    print(
        f"Slack Response: "
        f"{response.status}"
    )

    return response.status

# =====================================================
# MAIN
# =====================================================

def lambda_handler(
    event,
    context
):

    findings = (
        get_pending_notifications()
    )

    notifications_sent = 0

    for finding in findings:

        status = send_to_slack(
            finding
        )

        if status == 200:

            mark_notification_sent(
                finding[
                    "finding_id"
                ]
            )

            notifications_sent += 1

    return {

        "statusCode": 200,

        "body": json.dumps(

            {

                "pending_findings":
                len(findings),

                "notifications_sent":
                notifications_sent
            }
        )
    }