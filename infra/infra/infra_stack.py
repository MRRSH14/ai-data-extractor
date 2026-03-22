from aws_cdk import (
    Stack,
    CfnOutput,
    aws_lambda as _lambda,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
    aws_cloudwatch as cloudwatch,
    aws_sns_subscriptions as sns_subscriptions,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct
from aws_cdk.aws_apigatewayv2 import HttpApi, HttpMethod
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from aws_cdk import RemovalPolicy
from aws_cdk import Duration
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_sns import Topic as SnsTopic
from typing import cast
import os

class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tasks_table = dynamodb.Table(
            self,
            "TasksTable",
            partition_key=dynamodb.Attribute(
                name="task_id",
                type=dynamodb.AttributeType.STRING,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        dead_letter_queue = sqs.Queue(
            self,
            "DeadLetterQueue",
            retention_period=Duration.days(7),
        )

        tasks_queue = sqs.Queue(
            self,
            "TasksQueue",
            visibility_timeout=Duration.seconds(180),
            retention_period=Duration.days(1),
            receive_message_wait_time=Duration.seconds(0),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=dead_letter_queue,
            ),
        )
        
        cw_alarm = cloudwatch.Alarm(
            self,
            "DeadLetterQueueMessagesAlarm",
            metric=dead_letter_queue.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(1)
            ),
            threshold=3,
            evaluation_periods=5,
            datapoints_to_alarm=5,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "DLQ has more than 3 visible messages for 5 minutes. "
                "Investigate worker failures and redrive after fix."
            ),
        )

        alarm_topic = SnsTopic(
            self,
            "DeadLetterQueueMessagesAlarmTopic",
        )
        email = os.getenv("DLQ_ALERT_EMAIL")
        if email:
            sns_subscription = sns_subscriptions.EmailSubscription(
                email_address=email,
            )

            # Type-checkers can be overly strict about CDK subscription interface stubs.
            # Runtime behavior is fine.
            alarm_topic.add_subscription(sns_subscription)  # type: ignore[arg-type]

            # Use the correct CDK alarm action for SNS notifications.
            cw_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))  # type: ignore[arg-type]
        
        api_lambda = _lambda.Function(
            self,
            "AppLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="service.api_handler.handler",
            code=_lambda.Code.from_asset("../src"),
            environment={
                "TASKS_TABLE_NAME": tasks_table.table_name,
                "TASKS_QUEUE_URL": tasks_queue.queue_url,
            },
        )

        worker_lambda = _lambda.Function(
            self,
            "WorkerLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="worker.worker_handler.handler",
            code=_lambda.Code.from_asset("../src"),
            timeout=Duration.seconds(30),
            environment={
                "TASKS_TABLE_NAME": tasks_table.table_name,
            },
        )

        worker_lambda.add_event_source(
            SqsEventSource(
                tasks_queue,
                batch_size=1,
                max_batching_window=Duration.seconds(0),
            )
        )

        tasks_table.grant_read_write_data(api_lambda)

        tasks_queue.grant_send_messages(api_lambda)

        api_lambda_integration = HttpLambdaIntegration(
            "AppLambdaIntegration",
            handler=cast(_lambda.IFunction, api_lambda),
        )

        tasks_queue.grant_consume_messages(worker_lambda)
        tasks_table.grant_read_write_data(worker_lambda)

        http_api = HttpApi(
            self,
            "AwsAiPlatformServiceApi",
        )

        http_api.add_routes(
            path="/health",
            methods=[HttpMethod.GET],
            integration=api_lambda_integration,
        )

        http_api.add_routes(
            path="/hello",
            methods=[HttpMethod.GET],
            integration=api_lambda_integration,
        )

        http_api.add_routes(
            path="/tasks",
            methods=[HttpMethod.POST],
            integration=api_lambda_integration,
        )

        http_api.add_routes(
            path="/tasks/{id}",
            methods=[HttpMethod.GET],
            integration=api_lambda_integration,
        )

        CfnOutput(
            self,
            "ApiUrl",
            value=http_api.api_endpoint,
        )
        CfnOutput(
            self,
            "TasksQueueUrl",
            value=tasks_queue.queue_url,
            description="Main SQS queue URL (worker input).",
        )
        CfnOutput(
            self,
            "TasksQueueArn",
            value=tasks_queue.queue_arn,
            description="Main SQS queue ARN (redrive destination).",
        )
        CfnOutput(
            self,
            "DeadLetterQueueUrl",
            value=dead_letter_queue.queue_url,
            description="DLQ URL — failed messages after max receives.",
        )
        CfnOutput(
            self,
            "DeadLetterQueueArn",
            value=dead_letter_queue.queue_arn,
            description="DLQ ARN — use with StartMessageMoveTask / scripts.",
        )
        CfnOutput(
            self,
            "DeadLetterQueueAlarmTopicArn",
            value=alarm_topic.topic_arn,
            description="SNS topic for DLQ alarm (subscribe email here if not set at deploy).",
        )