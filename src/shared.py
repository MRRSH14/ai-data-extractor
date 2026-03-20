import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")


def json_response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def get_tasks_table():
    tasks_table_name = os.getenv("TASKS_TABLE_NAME")
    if not tasks_table_name:
        logger.error("TASKS_TABLE_NAME environment variable is not set")
        raise RuntimeError("Missing TASKS_TABLE_NAME environment variable")
    return dynamodb.Table(tasks_table_name)


def update_task_status(tasks_table, task_id: str, status: str) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        tasks_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":updated_at": updated_at,
            },
        )
    except ClientError:
        logger.exception(
            "Failed to update task status in DynamoDB. task_id=%s, status=%s",
            task_id,
            status,
        )
        raise

    logger.info("Task updated. task_id=%s, status=%s", task_id, status)
