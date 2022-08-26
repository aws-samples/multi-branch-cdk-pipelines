"""
Lambda function code used to create a CodeBuild project which deploys the CDK pipeline stack for the branch.
"""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client = boto3.client('codebuild')
region = os.environ['AWS_REGION']
account_id = os.environ['ACCOUNT_ID']
role_arn = os.environ['CODE_BUILD_ROLE_ARN']
artifact_bucket_name = os.environ['ARTIFACT_BUCKET']
codebuild_name_prefix = os.environ['CODEBUILD_NAME_PREFIX']


def generate_build_spec(branch: str):
    """Generates the build spec file used for the CodeBuild project"""
    return f"""version: 0.2
env:
  variables:
    BRANCH: {branch}
    DEV_ACCOUNT_ID: {account_id}
    PROD_ACCOUNT_ID: {account_id}
    REGION: {region}
phases:
  pre_build:
    commands:
      - npm install -g aws-cdk && pip install -r requirements.txt
  build:
    commands:
      - cdk synth
      - cdk deploy --require-approval=never
artifacts:
  files:
    - '**/*'"""


def handler(event, context):
    """Lambda function handler"""
    logger.info(event)

    reference_type = event['detail']['referenceType']

    try:
        if reference_type == 'branch':
            branch = event['detail']['referenceName']
            repo_name = event['detail']['repositoryName']

            client.create_project(
                name=f'{codebuild_name_prefix}-{branch}-create',
                description="Build project to deploy branch pipeline",
                source={
                    'type': 'CODECOMMIT',
                    'location': f'https://git-codecommit.{region}.amazonaws.com/v1/repos/{repo_name}',
                    'buildspec': generate_build_spec(branch)
                },
                sourceVersion=f'refs/heads/{branch}',
                artifacts={
                    'type': 'S3',
                    'location': artifact_bucket_name,
                    'path': f'{branch}',
                    'packaging': 'NONE',
                    'artifactIdentifier': 'BranchBuildArtifact'
                },
                environment={
                    'type': 'LINUX_CONTAINER',
                    'image': 'aws/codebuild/standard:6.0',
                    'computeType': 'BUILD_GENERAL1_SMALL'
                },
                serviceRole=role_arn
            )

            client.start_build(
                projectName=f'CodeBuild-{branch}-create'
            )
    except Exception as e:
        logger.error(e)
