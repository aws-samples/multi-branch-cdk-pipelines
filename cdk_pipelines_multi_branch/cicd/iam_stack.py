from aws_cdk.aws_iam import Role, PolicyStatement, ManagedPolicy, ServicePrincipal
from constructs import Construct


class IAMPipelineStack(Construct):
    def __init__(self,
                 scope: Construct,
                 construct_id: str,
                 account: str,
                 region: str,
                 repo_name: str,
                 artifact_bucket_arn: str,
                 codebuild_prefix: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM Role for the AWS Lambda function which creates the branch resources
        create_branch_role = Role(
            self,
            'LambdaCreateBranchRole',
            assumed_by=ServicePrincipal('lambda.amazonaws.com'))
        create_branch_role.add_managed_policy(
            ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))
        create_branch_role.add_to_policy(PolicyStatement(
            actions=[
                'codebuild:CreateProject',
                'codebuild:StartBuild'
            ],
            resources=[f'arn:aws:codebuild:{region}:{account}:project/{codebuild_prefix}*']
        ))

        # IAM Role for the AWS Lambda function which deletes the branch resources
        delete_branch_role = Role(
            self,
            'LambdaDeleteBranchRole',
            assumed_by=ServicePrincipal('lambda.amazonaws.com'))
        delete_branch_role.add_managed_policy(
            ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))
        delete_branch_role.add_to_policy(PolicyStatement(
            actions=[
                'codebuild:StartBuild',
                'codebuild:DeleteProject',
                'codebuild:CreateProject'
            ],
            resources=[f'arn:aws:codebuild:{region}:{account}:project/{codebuild_prefix}*']
        ))

        # IAM Role for the feature branch AWS CodeBuild project.
        code_build_role = Role(
            self,
            'CodeBuildExecutionRole',
            assumed_by=ServicePrincipal('codebuild.amazonaws.com'))
        code_build_role.add_to_policy(PolicyStatement(
            actions=['cloudformation:DescribeStacks', 'cloudformation:DeleteStack'],
            resources=[f'arn:aws:cloudformation:{region}:{account}:stack/*/*']
        ))
        code_build_role.add_to_policy(PolicyStatement(
            actions=['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
            resources=[
                f'arn:aws:logs:{region}:{account}:log-group:/aws/codebuild/{codebuild_prefix}-*',
                f'arn:aws:logs:{region}:{account}:log-group:/aws/codebuild/{codebuild_prefix}-*:*']
        ))
        code_build_role.add_to_policy(PolicyStatement(
            actions=['codecommit:Get*', 'codecommit:List*', 'codecommit:GitPull'],
            resources=[f'arn:aws:codecommit:{region}:{account}:{repo_name}']
        ))
        code_build_role.add_to_policy(PolicyStatement(
            actions=['s3:DeleteObject', 's3:PutObject', 's3:GetObject', 's3:ListBucket'],
            resources=[f'{artifact_bucket_arn}/*', f'{artifact_bucket_arn}']
        ))
        code_build_role.add_to_policy(PolicyStatement(
            actions=['sts:AssumeRole'],
            resources=[f'arn:*:iam::{account}:role/*'],
            conditions={
                "ForAnyValue:StringEquals": {
                    "iam:ResourceTag/aws-cdk:bootstrap-role": [
                        "image-publishing",
                        "file-publishing",
                        "deploy"
                    ]
                }
            }
        ))

        self.create_branch_role = create_branch_role
        self.delete_branch_role = delete_branch_role
        self.code_build_role = code_build_role
