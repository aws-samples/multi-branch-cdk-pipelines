#!/usr/bin/env python3
import configparser
import os

import aws_cdk as cdk
import boto3
import cdk_nag

from cdk_pipelines_multi_branch.cicd.cdk_pipelines_multi_branch_stack import CdkPipelinesMultiBranchStack

app = cdk.App()

# retrieve configuration variables
global_config = configparser.ConfigParser()
global_config.read('config.ini')
region = global_config.get('general', 'region')
codebuild_prefix = global_config.get('general', 'codebuild_project_name_prefix')
repository_name = global_config.get('general', 'repository_name')
current_branch = os.environ['BRANCH']

# retrieve the default branch by the CodeCommit repository
codecommit_client = boto3.client('codecommit', region_name=region)
repository = codecommit_client.get_repository(
    repositoryName=repository_name
)
default_branch = repository['repositoryMetadata']['defaultBranch']

config = {
    'dev_account_id': os.environ['DEV_ACCOUNT_ID'],
    'branch': current_branch,
    'default_branch': default_branch,
    'region': region,
    'codebuild_prefix': codebuild_prefix,
    'repository_name': repository_name
}

# Only the default branch resources will be deployed to the production environment.
if current_branch == default_branch:
    config['prod_account_id'] = os.environ['PROD_ACCOUNT_ID']

CdkPipelinesMultiBranchStack(
    app,
    f"cdk-pipelines-multi-branch-{current_branch}",
    config,
    env=cdk.Environment(account=config['dev_account_id'], region=region)
)

cdk.Aspects.of(app).add(cdk_nag.AwsSolutionsChecks())

app.synth()
