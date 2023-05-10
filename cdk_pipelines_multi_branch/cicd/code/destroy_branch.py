import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client = boto3.client('codebuild')
region = os.environ['AWS_REGION']
role_arn = os.environ['CODE_BUILD_ROLE_ARN']
account_id = os.environ['ACCOUNT_ID']
artifact_bucket_name = os.environ['ARTIFACT_BUCKET']
codebuild_name_prefix = os.environ['CODEBUILD_NAME_PREFIX']
dev_stage_name = os.environ['DEV_STAGE_NAME']


def generate_build_spec(branch):
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
      - cdk destroy cdk-pipelines-multi-branch-{branch} --force
      - aws cloudformation delete-stack --stack-name {dev_stage_name}-{branch}
      - aws s3 rm s3://{artifact_bucket_name}/{branch} --recursive"""


def handler(event, context):
    logger.info(event)
    reference_type = event['detail']['referenceType']

    try:
        if reference_type == 'branch':
            branch = event['detail']['referenceName']
            client.create_project(
                name=f'{codebuild_name_prefix}-{branch}-destroy',
                description="Build project to destroy branch resources",
                source={
                    'type': 'S3',
                    'location': f'{artifact_bucket_name}/{branch}/CodeBuild-{branch}-create/',
                    'buildspec': generate_build_spec(branch)
                },
                artifacts={
                    'type': 'NO_ARTIFACTS'
                },
                environment={
                    'type': 'LINUX_CONTAINER',
                    'image': 'aws/codebuild/standard:6.0',
                    'computeType': 'BUILD_GENERAL1_SMALL'
                },
                serviceRole=role_arn
            )

            client.start_build(
                projectName=f'{codebuild_name_prefix}-{branch}-destroy'
            )

            client.delete_project(
                name=f'{codebuild_name_prefix}-{branch}-destroy'
            )

            client.delete_project(
                name=f'{codebuild_name_prefix}-{branch}-create'
            )
    except Exception as e:
        logger.error(e)
