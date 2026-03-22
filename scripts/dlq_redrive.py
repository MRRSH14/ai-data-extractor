#!/usr/bin/env python3
"""
Inspect the tasks DLQ and redrive messages back to the main queue.

Requires: pip install boto3

Examples:
  # Queue URLs from CloudFormation stack outputs (InfraStack)
  export DLQ_URL="https://sqs....amazonaws.com/.../InfraStack-DeadLetterQueue..."
  export MAIN_URL="https://sqs....amazonaws.com/.../InfraStack-TasksQueue..."

  python scripts/dlq_redrive.py stats --dlq-url "$DLQ_URL"
  python scripts/dlq_redrive.py peek --dlq-url "$DLQ_URL" --max 5
  python scripts/dlq_redrive.py redrive --dlq-url "$DLQ_URL" --destination-url "$MAIN_URL"

  # Or pass ARNs (needed for AWS native move task):
  python scripts/dlq_redrive.py redrive --dlq-arn "$DLQ_ARN" --destination-arn "$MAIN_ARN"
"""

from __future__ import annotations

import argparse
import json
import sys


def _client(region: str | None, profile: str | None):
    try:
        import boto3
    except ImportError as e:
        print("Install boto3: pip install boto3", file=sys.stderr)
        raise SystemExit(1) from e

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("sqs")


def cmd_stats(args: argparse.Namespace) -> int:
    sqs = _client(args.region, args.profile)
    attrs = sqs.get_queue_attributes(
        QueueUrl=args.dlq_url,
        AttributeNames=["All"],
    )["Attributes"]
    # AWS names the visible/available count ApproximateNumberOfMessages (not ...Visible).
    available = attrs.get("ApproximateNumberOfMessages", "?")
    not_visible = attrs.get("ApproximateNumberOfMessagesNotVisible", "?")
    print(f"ApproximateNumberOfMessages (available):     {available}")
    print(f"ApproximateNumberOfMessagesNotVisible (in flight): {not_visible}")
    return 0


def cmd_peek(args: argparse.Namespace) -> int:
    sqs = _client(args.region, args.profile)
    remaining = args.max
    total = 0
    while remaining > 0:
        batch = min(remaining, 10)
        resp = sqs.receive_message(
            QueueUrl=args.dlq_url,
            MaxNumberOfMessages=batch,
            WaitTimeSeconds=min(10, args.wait),
            VisibilityTimeout=0,
            AttributeNames=["All"],
        )
        messages = resp.get("Messages") or []
        if not messages:
            break
        for m in messages:
            total += 1
            print("--- message ---")
            print(json.dumps(m, indent=2, default=str))
        remaining -= len(messages)
    if total == 0:
        print("No messages received (queue may be empty).")
    return 0


def cmd_redrive(args: argparse.Namespace) -> int:
    sqs = _client(args.region, args.profile)
    dlq_arn = args.dlq_arn
    dest_arn = args.destination_arn
    if not dlq_arn or not dest_arn:
        if not args.dlq_url or not args.destination_url:
            print(
                "Provide either (--dlq-arn and --destination-arn) or "
                "(--dlq-url and --destination-url).",
                file=sys.stderr,
            )
            return 2
        attrs = sqs.get_queue_attributes(
            QueueUrl=args.dlq_url,
            AttributeNames=["QueueArn"],
        )
        dlq_arn = attrs["Attributes"]["QueueArn"]
        attrs = sqs.get_queue_attributes(
            QueueUrl=args.destination_url,
            AttributeNames=["QueueArn"],
        )
        dest_arn = attrs["Attributes"]["QueueArn"]

    try:
        resp = sqs.start_message_move_task(
            SourceArn=dlq_arn,
            DestinationArn=dest_arn,
        )
    except AttributeError:
        print(
            "start_message_move_task not available in this boto3 version; "
            "using receive → send → delete loop.",
            file=sys.stderr,
        )
        if not args.dlq_url or not args.destination_url:
            print(
                "Poll redrive requires --dlq-url and --destination-url "
                "(upgrade boto3 to use native redrive with ARNs only).",
                file=sys.stderr,
            )
            return 2
        return _redrive_poll(sqs, args.dlq_url, args.destination_url)
    else:
        print("Started DLQ redrive task (AWS moves messages asynchronously).")
        print(json.dumps(resp, indent=2, default=str))
        print(
            "\nCheck progress in the SQS console: DLQ → 'DLQ redrive' history, "
            "or poll destination queue depth.",
        )
        return 0


def _redrive_poll(sqs, dlq_url: str, dest_url: str) -> int:
    moved = 0
    while True:
        resp = sqs.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=10,
            VisibilityTimeout=300,
        )
        messages = resp.get("Messages") or []
        if not messages:
            break
        for m in messages:
            sqs.send_message(QueueUrl=dest_url, MessageBody=m["Body"])
            sqs.delete_message(
                QueueUrl=dlq_url,
                ReceiptHandle=m["ReceiptHandle"],
            )
            moved += 1
            print(f"Moved message {m.get('MessageId', '?')} ({moved} total)")
    print(f"Done. Moved {moved} message(s).")
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--profile",
        help="AWS CLI profile name (optional).",
    )
    common.add_argument(
        "--region",
        help="AWS region (optional; else default from profile/env).",
    )

    parser = argparse.ArgumentParser(
        description="DLQ stats, peek, and redrive for SQS.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("stats", parents=[common], help="DLQ depth (visible / in flight).")
    p_stats.add_argument("--dlq-url", required=True, help="Dead-letter queue URL.")
    p_stats.set_defaults(func=cmd_stats)

    p_peek = sub.add_parser(
        "peek",
        parents=[common],
        help="Receive with VisibilityTimeout=0 (non-destructive sample; may be racy).",
    )
    p_peek.add_argument("--dlq-url", required=True)
    p_peek.add_argument("--max", type=int, default=10, help="Max messages to print.")
    p_peek.add_argument("--wait", type=int, default=10, help="Long-poll wait seconds per batch.")
    p_peek.set_defaults(func=cmd_peek)

    p_redrive = sub.add_parser(
        "redrive",
        parents=[common],
        help="Move all messages from DLQ to the main queue.",
    )
    p_redrive.add_argument("--dlq-url", help="Dead-letter queue URL.")
    p_redrive.add_argument("--destination-url", help="Main (source) queue URL.")
    p_redrive.add_argument(
        "--dlq-arn",
        help="Dead-letter queue ARN (optional if --dlq-url given).",
    )
    p_redrive.add_argument(
        "--destination-arn",
        help="Main queue ARN (optional if --destination-url given).",
    )
    p_redrive.set_defaults(func=cmd_redrive)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
