from typing import Dict, Optional

import boto3


class PullRequestClient:
    def __init__(self):
        self.client = boto3.client('codecommit')

    def get_pr_details_by_id(self, pr_id):
        pull_request = self.client.get_pull_request(pullRequestId=pr_id)
        return pull_request['pullRequest']

    def find_open_pr_by_destination_reference(self, repository_name: str, destination_reference: str) -> Optional[Dict]:
        paginator = self.client.get_paginator('list_pull_requests')

        response_iterator = paginator.paginate(repositoryName=repository_name, pullRequestStatus='OPEN', )

        for response in response_iterator:
            for pull_request_id in response['pullRequestIds']:
                pull_request_details = self.get_pr_details_by_id(pull_request_id)

                targets = list(filter(lambda target: target['sourceReference'] == destination_reference,
                                      pull_request_details['pullRequestTargets'], ))

                if not targets:
                    continue

                return pull_request_details

        return None

    def approve_pr(self, pull_request_id: str, revision_id: str, with_role: str = '') -> None:
        codecommit_client = self.client

        if with_role:
            sts_client = boto3.client('sts')
            assumed_role_object = sts_client.assume_role(
                RoleArn=with_role,
                RoleSessionName="AssumeRoleSession"
            )
            credentials = assumed_role_object['Credentials']
            codecommit_client = boto3.client(
                'codecommit',
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
            )

        codecommit_client.update_pull_request_approval_state(pullRequestId=pull_request_id, revisionId=revision_id,
                                                             approvalState='APPROVE')


if __name__ == '__main__':
    client = PullRequestClient()
    print(client.find_open_pr_by_destination_reference('cdk-pipelines-multi-branch', 'refs/heads/user-feature-123'))
