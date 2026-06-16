import json
import os
import boto3
import urllib.parse
import base64
from datetime import datetime

# =====================================================
# AWS
# =====================================================

dynamodb = boto3.resource(
    "dynamodb"
)

table = dynamodb.Table(
    os.environ["TABLE_NAME"]
)

# =====================================================
# MAIN
# =====================================================

def lambda_handler(
    event,
    context
):

    try:

        body = event["body"]

        # ---------------------------------------------
        # Decode Base64 Payload
        # ---------------------------------------------

        if event.get(
            "isBase64Encoded",
            False
        ):

            body = (
                base64
                .b64decode(body)
                .decode("utf-8")
            )

        # ---------------------------------------------
        # Parse Slack Payload
        # ---------------------------------------------

        parsed = (
            urllib.parse.parse_qs(
                body
            )
        )

        payload = json.loads(
            parsed["payload"][0]
        )

        action = (
            payload["actions"][0]
        )

        action_id = (
            action["action_id"]
        )

        finding_id = (
            action["value"]
        )

        timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        # ---------------------------------------------
        # Get Finding Details
        # ---------------------------------------------

        response = table.get_item(
            Key={
                "finding_id":
                finding_id
            }
        )

        item = response.get(
            "Item",
            {}
        )

        if not item:

            return {
                "statusCode": 404,
                "body": json.dumps(
                    {
                        "text":
                        f"Finding {finding_id} not found."
                    }
                )
            }

        # ---------------------------------------------
        # APPROVE
        # ---------------------------------------------

        if action_id == "approve":

            table.update_item(
                Key={
                    "finding_id":
                    finding_id
                },
                UpdateExpression=
                """
                SET #s = :status,
                    approved_at = :time
                """,
                ExpressionAttributeNames={
                    "#s":
                    "status"
                },
                ExpressionAttributeValues={
                    ":status":
                    "APPROVED",

                    ":time":
                    timestamp
                }
            )

            response_text = (
                f"✅ Finding Approved\n\n"
                f"Resource Name: "
                f"{item.get('resource_name','N/A')}\n"
                f"Resource Type: "
                f"{item.get('resource_type','N/A')}\n"
                f"Finding Type: "
                f"{item.get('finding_type','N/A')}\n"
                f"Finding ID: "
                f"{finding_id}"
            )

        # ---------------------------------------------
        # REJECT
        # ---------------------------------------------

        elif action_id == "reject":

            table.update_item(
                Key={
                    "finding_id":
                    finding_id
                },
                UpdateExpression=
                """
                SET #s = :status,
                    rejected_at = :time
                """,
                ExpressionAttributeNames={
                    "#s":
                    "status"
                },
                ExpressionAttributeValues={
                    ":status":
                    "REJECTED",

                    ":time":
                    timestamp
                }
            )

            response_text = (
                f"❌ Finding Rejected\n\n"
                f"Resource Name: "
                f"{item.get('resource_name','N/A')}\n"
                f"Resource Type: "
                f"{item.get('resource_type','N/A')}\n"
                f"Finding Type: "
                f"{item.get('finding_type','N/A')}\n"
                f"Finding ID: "
                f"{finding_id}"
            )

        else:

            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "text":
                        "Unknown action."
                    }
                )
            }

        print(
            f"Finding {finding_id} "
            f"updated successfully."
        )

        return {

            "statusCode": 200,

            "headers": {
                "Content-Type":
                "application/json"
            },

            "body": json.dumps(
                {
                    "text":
                    response_text
                }
            )
        }

    except Exception as e:

        print(
            f"ERROR: {str(e)}"
        )

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error":
                    str(e)
                }
            )
        }