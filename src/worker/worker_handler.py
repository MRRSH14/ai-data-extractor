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

    task_id = message.get("task_id")
    if not task_id:
        logger.error("task_id is missing in SQS message: %s", message)
        raise ValueError("task_id is missing in SQS message")

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

    processed = 0
    failed = 0
    for record in records:
        message_id = record.get("messageId")
        receive_count = (record.get("attributes") or {}).get(
            "ApproximateReceiveCount"
        )
        try:
            process_record(tasks_table, record)
            processed += 1
            logger.info(
                "Record processed successfully. message_id=%s receive_count=%s",
                message_id,
                receive_count,
            )
        except ValueError as exc:
            # Known data/validation issues are terminal for this task.
            logger.exception(
                "Known processing error. message_id=%s receive_count=%s error=%s",
                message_id,
                receive_count,
                exc,
            )
            failed += 1
            try:
                task_id = parse_task_id_from_record(record)
                update_task_status(tasks_table, task_id, "failed")
                logger.info(
                    "Marked task as failed. task_id=%s message_id=%s receive_count=%s",
                    task_id,
                    message_id,
                    receive_count,
                )
            except ValueError:
                logger.exception(
                    "Skipping failed status update: could not extract task_id. "
                    "message_id=%s receive_count=%s",
                    message_id,
                    receive_count,
                )
            except Exception:
                logger.exception(
                    "Failed to mark task as failed. message_id=%s receive_count=%s",
                    message_id,
                    receive_count,
                )

    return {"processed": processed, "failed": failed}
