from aws_cdk import Stage, Stack
from constructs import Construct

from .s3trigger.s3trigger_stack import S3TriggerConstruct


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, branch: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # - combines single constructs in src/ to one stack
        S3TriggerConstruct(self, f'S3Trigger-${branch}')


class MainStage(Stage):

    def __init__(self, scope: Construct, construct_id: str, branch: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        main_stack_name = 'InfraStack'
        InfraStack(self, f'{main_stack_name}-{branch}', branch)

        self.main_stack_name = main_stack_name
