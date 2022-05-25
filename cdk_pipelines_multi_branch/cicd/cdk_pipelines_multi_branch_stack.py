from os import path

from aws_cdk import (
    Stack, aws_codepipeline_actions, Aspects, RemovalPolicy
)
from aws_cdk.aws_codecommit import Repository
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_iam import PolicyStatement
from aws_cdk.aws_lambda import Function, Runtime, Code
from aws_cdk.aws_s3 import BucketEncryption
from aws_cdk.pipelines import CodePipeline, CodeBuildStep, CodePipelineSource, ManualApprovalStep
from cdk_nag import NagSuppressions, NagPackSuppression
from constructs import Construct

from cdk_pipelines_multi_branch.cicd.aspects.key_rotation_aspect import KeyRotationAspect
from .constructs.standard_bucket import S3Construct
from .iam_stack import IAMPipelineStack
from ..src.application_stage import MainStage as Application


class CdkPipelinesMultiBranchStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, config: object, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        this_dir = path.dirname(__file__)

        codebuild_prefix = config['codebuild_prefix']
        region = config['region']
        repo_name = config['repository_name']
        branch = config['branch']
        default_branch = config['default_branch']
        dev_account_id = config['dev_account_id']
        prod_account_id = config['prod_account_id'] if branch == default_branch else dev_account_id

        repo = Repository.from_repository_name(self, 'ImportedRepo', repo_name)

        pipeline = CodePipeline(
            self,
            f"Pipeline-{branch}",
            pipeline_name=f"CICDPipeline-{branch}",
            cross_account_keys=True,
            synth=CodeBuildStep(
                'Synth',
                input=CodePipelineSource.code_commit(
                    repository=repo,
                    trigger=aws_codepipeline_actions.CodeCommitTrigger.POLL,
                    branch=branch
                ),
                env={
                    'BRANCH': branch,
                    'DEV_ACCOUNT_ID': dev_account_id,
                    'PROD_ACCOUNT_ID': prod_account_id
                },
                install_commands=[
                    'gem install cfn-nag',
                    'npm install -g aws-cdk',
                    'pip install -r requirements.txt',
                    'export LC_ALL="en_US.UTF-8"',
                    'locale-gen en_US en_US.UTF-8',
                    'dpkg-reconfigure locales'
                ],
                commands=[
                    f'cdk synth',
                    f'npx cdk synth cdk-pipelines-multi-branch-{branch}/DEV/InfraStack-{branch} > infra_stack.yaml',
                    'cfn_nag_scan --input-path infra_stack.yaml'
                ],
                role_policy_statements=[
                    PolicyStatement(
                        actions=[
                            'codecommit:GetRepository'
                        ],
                        resources=[
                            f'arn:aws:codecommit:{region}:{dev_account_id}:{repo_name}'
                        ])
                ]
            ))

        Aspects.of(self).add(KeyRotationAspect())

        dev_stage_name = 'DEV'
        dev_stage = Application(self, dev_stage_name, branch, env={'account': dev_account_id, 'region': region})
        pipeline.add_stage(dev_stage)

        if branch == default_branch:
            # Prod stage
            pipeline.add_stage(Application(self, 'PROD', branch, env={'account': prod_account_id, 'region': region}),
                               pre=[ManualApprovalStep('ManualApproval', comment='Pre-prod manual approval')])

            # Artifact bucket for feature AWS CodeBuild projects
            args = dict(
                encryption=BucketEncryption.KMS_MANAGED,
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True
            )
            artifact_bucket = S3Construct(self, 'BranchArtifacts', args).bucket

            # AWS Lambda and AWS CodeBuild projects' IAM Roles.
            iam_stack = IAMPipelineStack(
                self,
                'IAMPipeline',
                account=dev_account_id,
                region=region,
                repo_name=repo_name,
                artifact_bucket_arn=artifact_bucket.bucket_arn,
                codebuild_prefix=codebuild_prefix)

            # AWS Lambda function triggered upon branch creation
            create_branch_func = Function(
                self,
                'LambdaTriggerCreateBranch',
                runtime=Runtime.PYTHON_3_9,
                function_name='LambdaTriggerCreateBranch',
                handler='create_branch.handler',
                code=Code.from_asset(path.join(this_dir, 'code')),
                environment={
                    "ACCOUNT_ID": dev_account_id,
                    "CODE_BUILD_ROLE_ARN": iam_stack.code_build_role.role_arn,
                    "ARTIFACT_BUCKET": artifact_bucket.bucket_name,
                    "CODEBUILD_NAME_PREFIX": codebuild_prefix
                },
                role=iam_stack.create_branch_role)

            # Configure AWS CodeCommit to trigger the Lambda function when new branch is created
            repo.on_reference_created(
                'BranchCreateTrigger',
                description="AWS CodeCommit reference created event.",
                target=LambdaFunction(create_branch_func))

            # AWS Lambda function triggered upon branch deletion
            destroy_branch_func = Function(
                self,
                'LambdaTriggerDestroyBranch',
                runtime=Runtime.PYTHON_3_9,
                function_name='LambdaTriggerDestroyBranch',
                handler='destroy_branch.handler',
                role=iam_stack.delete_branch_role,
                environment={
                    "ACCOUNT_ID": dev_account_id,
                    "CODE_BUILD_ROLE_ARN": iam_stack.code_build_role.role_arn,
                    "ARTIFACT_BUCKET": artifact_bucket.bucket_name,
                    "CODEBUILD_NAME_PREFIX": codebuild_prefix,
                    "DEV_STAGE_NAME": f'{dev_stage_name}-{dev_stage.main_stack_name}'
                },
                code=Code.from_asset(path.join(this_dir,
                                               'code')))

            # Configure AWS CodeCommit to trigger the Lambda function when a branch is deleted
            repo.on_reference_deleted(
                'BranchDeleteTrigger',
                description="AWS CodeCommit reference deleted event.",
                target=LambdaFunction(destroy_branch_func))

        # CDK Nag supressions
        NagSuppressions.add_stack_suppressions(self, [
            NagPackSuppression(
                id='AwsSolutions-IAM5',
                reason='Wildcard permissions for CDK Pipelines resources are allowed.'
            )
        ], True)

        NagSuppressions.add_stack_suppressions(self, [
            NagPackSuppression(
                id='AwsSolutions-KMS5',
                reason='Fault positive: KMS Key rotation enabled using Aspects.'
            )
        ], True)

        NagSuppressions.add_stack_suppressions(self, [
            NagPackSuppression(
                id='AwsSolutions-S1',
                reason='Server Access Logging not required.'
            )
        ], True)

        NagSuppressions.add_stack_suppressions(self, [
            NagPackSuppression(
                id='AwsSolutions-IAM4',
                reason='Lambda can use AWS Lambda managed policy'
            )
        ], True)
