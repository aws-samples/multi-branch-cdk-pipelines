from os import path

from aws_cdk import core, aws_events_targets, aws_lambda, aws_codepipeline_actions
from aws_cdk.aws_codecommit import Repository
from aws_cdk.aws_iam import PolicyStatement
from aws_cdk.aws_s3 import Bucket, BucketEncryption
from aws_cdk.core import RemovalPolicy
from aws_cdk.pipelines import CodePipeline, ManualApprovalStep, CodePipelineSource, CodeBuildStep

from src.application_stage import MainStage as Application
from .iam.iam_stack import IAMPipelineStack


class PipelineStack(core.Stack):

    def __init__(self, scope: core.Construct, construct_id: str, config: object,
                 **kwargs) -> None:
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

        dev_stage_name = 'DEV'
        dev_stage = Application(self, dev_stage_name, branch, env={'account': dev_account_id, 'region': region})
        pipeline.add_stage(dev_stage)

        if branch == default_branch:
            # Prod stage
            pipeline.add_stage(Application(self, 'PROD', branch, env={'account': prod_account_id, 'region': region}),
                               pre=[ManualApprovalStep('ManualApproval', comment='Pre-prod manual approval')])

            # Artifact bucket for feature AWS CodeBuild projects
            artifact_bucket = Bucket(
                self,
                'BranchArtifacts',
                encryption=BucketEncryption.KMS_MANAGED,
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True
            )

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
            create_branch_func = aws_lambda.Function(
                self,
                'LambdaTriggerCreateBranch',
                runtime=aws_lambda.Runtime.PYTHON_3_8,
                function_name='LambdaTriggerCreateBranch',
                handler='create_branch.handler',
                code=aws_lambda.Code.from_asset(path.join(this_dir, 'code')),
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
                target=aws_events_targets.LambdaFunction(create_branch_func))

            # AWS Lambda function triggered upon branch deletion
            destroy_branch_func = aws_lambda.Function(
                self,
                'LambdaTriggerDestroyBranch',
                runtime=aws_lambda.Runtime.PYTHON_3_8,
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
                code=aws_lambda.Code.from_asset(path.join(this_dir,
                                                          'code')))

            # Configure AWS CodeCommit to trigger the Lambda function when a branch is deleted
            repo.on_reference_deleted(
                'BranchDeleteTrigger',
                description="AWS CodeCommit reference deleted event.",
                target=aws_events_targets.LambdaFunction(destroy_branch_func))
