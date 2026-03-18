import json
import time

from shared import logger, get_tasks_table, update_task_status


def parse_task_id_from_record(record: dict) -> str:
    body = record.get("body")
    if not body:
        logger.error("SQS record body is missing")
        raise ValueError("SQS record body is missing")

    try:
        message = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in SQS message body: %s", body)
        raise ValueError("Invalid JSON in SQS message body")

    task_id = message.get("taskId")
    if not task_id:
        logger.error("taskId is missing in SQS message: %s", message)
        raise ValueError("taskId is missing in SQS message")

    return task_id


def process_record(tasks_table, record: dict) -> None:
    task_id = parse_task_id_from_record(record)

    update_task_status(tasks_table, task_id, "running")

    # Simulate background work for now.
    time.sleep(20)

    update_task_status(tasks_table, task_id, "completed")


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        logger.warning("No SQS records received")
        return {"processed": 0}

    tasks_table = get_tasks_table()

    logger.info("Received %d SQS record(s)", len(records))

    for record in records:
        process_record(tasks_table, record)

    return {"processed": len(records)}