import click
from cicd.pull_requests import PullRequestClient


@click.group()
def cli():
    pass


@click.command()
@click.option('--pull-request-id', help='Pull request id', required=True)
@click.option('--revision-id', help='Revision id', required=True)
@click.option('--with-role', help='Role to be used for approving the PR', required=False)
def approve_pr(pull_request_id: str, revision_id: str, with_role: str = ''):
    pull_request_client = PullRequestClient()
    pull_request_client.approve_pr(pull_request_id, revision_id, with_role=with_role)


cli.add_command(approve_pr)

if __name__ == '__main__':
    cli()
