from os import path, environ
from typing import Dict, Any

from aws_cdk import core, aws_events_targets, aws_lambda
from aws_cdk.aws_codecommit import Repository
from aws_cdk.aws_s3 import Bucket, BucketEncryption
from aws_cdk.core import RemovalPolicy, Stack
from aws_cdk.aws_codebuild import BuildEnvironment, ComputeType
from aws_cdk.pipelines import CodePipeline, ManualApprovalStep, CodePipelineSource, CodeBuildStep, ShellStep, \
    StageDeployment
from aws_cdk.aws_iam import Role, PolicyStatement, ServicePrincipal, Effect, ArnPrincipal
from cicd.pull_requests import PullRequestClient
from src.application_stage import MainStage as Application
from .iam.iam_stack import IAMPipelineStack
from cloudcomponents.cdk_pull_request_approval_rule import ApprovalRuleTemplate, Template, Approvers, \
    ApprovalRuleTemplateRepositoryAssociation


class PipelineStack(core.Stack):

    def __init__(self, scope: core.Construct, construct_id: str, config: Dict[str, Any],
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.dev_stage_name = 'DEV'
        self.dev_account_id = config['dev_account_id']
        self.current_branch = config['branch']
        self.default_branch = config['default_branch']
        self.prod_account_id = config[
            'prod_account_id'] if self.current_branch == self.default_branch else self.dev_account_id
        self.config = config
        self.repo = Repository.from_repository_name(self, 'ImportedRepo', config['repository_name'])

        pipeline = CodePipeline(
            self,
            f"Pipeline-{self.current_branch}",
            pipeline_name=f"CICDPipeline-{self.current_branch}",
            cross_account_keys=True,
            synth=CodeBuildStep(
                'Synth',
                input=CodePipelineSource.code_commit(repository=self.repo, branch=self.current_branch),
                build_environment=BuildEnvironment(compute_type=ComputeType.MEDIUM),
                env={
                    'BRANCH': self.current_branch,
                    'DEV_ACCOUNT_ID': self.dev_account_id,
                    'PROD_ACCOUNT_ID': self.prod_account_id
                },
                install_commands=[
                    'npm install -g aws-cdk',
                    'pip install -r requirements.txt',
                ],
                commands=[
                    f'cdk synth',
                    f'npx cdk synth cdk-pipelines-multi-branch-{self.current_branch}/DEV/InfraStack-{self.current_branch}',
                ],
                role_policy_statements=[
                    PolicyStatement(
                        actions=['codecommit:*', 'codecommit:ListPullRequests', 'codecommit:GetPullRequest', ],
                        resources=[
                            f'arn:aws:codecommit:{self.region}:{self.dev_account_id}:{self.repo.repository_name}'])
                ]
            ))

        dev_stage = Application(self, self.dev_stage_name, self.current_branch,
                                env={'account': self.dev_account_id, 'region': self.region})
        dev_stage_deployment = pipeline.add_stage(dev_stage)

        self.__configure_prod_stage(pipeline, dev_stage)
        self.__configure_pr_auto_approval(dev_stage_deployment)

    def __configure_prod_stage(self, pipeline: CodePipeline, dev_stage: Application):
        if self.current_branch != self.default_branch:
            return

        this_dir = path.dirname(__file__)
        codebuild_prefix = self.config['codebuild_prefix']
        # Prod stage
        pipeline.add_stage(
            Application(self, 'PROD', self.current_branch,
                        env={'account': self.prod_account_id, 'region': self.region}),
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
            account=self.dev_account_id,
            region=self.region,
            repo_name=self.repo.repository_name,
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
                "ACCOUNT_ID": self.dev_account_id,
                "CODE_BUILD_ROLE_ARN": iam_stack.code_build_role.role_arn,
                "ARTIFACT_BUCKET": artifact_bucket.bucket_name,
                "CODEBUILD_NAME_PREFIX": codebuild_prefix
            },
            role=iam_stack.create_branch_role)

        # Configure AWS CodeCommit to trigger the Lambda function when new branch is created
        self.repo.on_reference_created(
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
                "ACCOUNT_ID": self.dev_account_id,
                "CODE_BUILD_ROLE_ARN": iam_stack.code_build_role.role_arn,
                "ARTIFACT_BUCKET": artifact_bucket.bucket_name,
                "CODEBUILD_NAME_PREFIX": codebuild_prefix,
                "DEV_STAGE_NAME": f'{self.dev_stage_name}-{dev_stage.main_stack_name}'
            },
            code=aws_lambda.Code.from_asset(path.join(this_dir, 'code')))

        # Configure AWS CodeCommit to trigger the Lambda function when a branch is deleted
        self.repo.on_reference_deleted('BranchDeleteTrigger',
                                       description="AWS CodeCommit reference deleted event.",
                                       target=aws_events_targets.LambdaFunction(destroy_branch_func))

    def __configure_pr_auto_approval(self, stage: StageDeployment) -> None:
        if self.config.get('enable_pr_auto_approval', 'false').lower() == 'false':
            return

        role_name = self.__get_role_name(f'pr-automated-approvals-{self.repo.repository_name}')

        # Check if there is PR for this branch
        pull_request_client = PullRequestClient()
        pull_request_details = pull_request_client.find_open_pr_by_destination_reference(
            self.repo.repository_name, f'refs/heads/{environ["BRANCH"]}')

        if pull_request_details:
            # If there is a pull request for this branch then we create a post build step that will approve the PR
            # For this we need to allow this role to assume the one that is used in the approval template
            # Dedicated user for approving pull requests on successful build
            # Only create on the default branch as the role is unique
            role_name = self.__get_role_name(
                f'codebuild-step-pr-approval-{self.repo.repository_name}-{self.current_branch}')

            rule_template_name = f'PrAutomatedApprovals{self.repo.repository_name}{self.current_branch}'
            approval_template = ApprovalRuleTemplate(self, 'AutomatedPulLRequestApprovalTemplate',
                                                     approval_rule_template_name=rule_template_name,
                                                     template=Template(
                                                         approvers=Approvers(number_of_approvals_needed=1,
                                                                             approval_pool_members=[
                                                                                 f'CodeCommitApprovers:{role_name}'])))

            assoc = ApprovalRuleTemplateRepositoryAssociation(self,
                                                              f'PrAutomatedApprovalAssociation{self.repo.repository_name}',
                                                              approval_rule_template_name=rule_template_name,
                                                              repository=self.repo)
            assoc.node.add_dependency(approval_template)

            pr_approval_build_step_role = Role(self, 'ExecutePRApprovalRole', role_name=role_name,
                                               assumed_by=ServicePrincipal('codebuild.amazonaws.com'))
            pr_approval_build_step_role.add_to_policy(PolicyStatement(
                resources=[f'arn:aws:codecommit:{self.region}:{self.dev_account_id}:{self.repo.repository_name}'],
                actions=['codecommit:UpdatePullRequestApprovalState']))

            commands = ["PYTHONPATH=$(pwd)", "python cicd/scripts/cli.py", "approve-pr",
                        "--pull-request-id", pull_request_details['pullRequestId'], "--revision-id",
                        pull_request_details['revisionId']]
            pr_approval_build_step = CodeBuildStep("Approve Pull Request", commands=[" ".join(commands)],
                                                   role=pr_approval_build_step_role)
            stage.add_post(pr_approval_build_step)

    @staticmethod
    def __get_role_name(role_name: str) -> str:
        final_role_name = role_name

        if len(role_name) > 64:
            role_name_hash = hex(hash(role_name) & 0xffffffff)[2:]
            final_role_name = role_name[0: 64 - len(role_name_hash)] + role_name_hash

        return final_role_name
