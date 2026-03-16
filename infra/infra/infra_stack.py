from aws_cdk import (
    Stack,
    CfnOutput,
    aws_lambda as _lambda,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
)
from constructs import Construct
from aws_cdk.aws_apigatewayv2 import HttpApi, HttpMethod
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tasks_table = dynamodb.Table(
            self,
            "TasksTable",
            partition_key=dynamodb.Attribute(
                name="taskId",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        tasks_queue = sqs.Queue(
            self,
            "TasksQueue",
        )

        app_lambda = _lambda.Function(
            self,
            "AppLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../service/src"),
            environment={
                "TASKS_TABLE_NAME": tasks_table.table_name,
                "TASKS_QUEUE_URL": tasks_queue.queue_url,
            },
        )

        tasks_table.grant_read_write_data(app_lambda)

        tasks_queue.grant_send_messages(app_lambda)

        app_lambda_integration = HttpLambdaIntegration(
            "AppLambdaIntegration",
            handler=app_lambda,
        )

        http_api = HttpApi(
            self,
            "AwsAiPlatformServiceApi",
        )

        http_api.add_routes(
            path="/health",
            methods=[HttpMethod.GET],
            integration=app_lambda_integration,
        )

        http_api.add_routes(
            path="/hello",
            methods=[HttpMethod.GET],
            integration=app_lambda_integration,
        )

        http_api.add_routes(
            path="/tasks",
            methods=[HttpMethod.POST],
            integration=app_lambda_integration,
        )

        http_api.add_routes(
            path="/tasks/{id}",
            methods=[HttpMethod.GET],
            integration=app_lambda_integration,
        )

        CfnOutput(
            self,
            "ApiUrl",
            value=http_api.api_endpoint,
        )