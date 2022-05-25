from aws_cdk import App, RemovalPolicy
from aws_cdk.aws_iam import PolicyStatement, Effect, ServicePrincipal, AnyPrincipal
from aws_cdk.aws_kms import Key
from aws_cdk.aws_s3 import Bucket, BucketEncryption, BlockPublicAccess
from constructs import Construct


class S3Construct(Construct):
    def __init__(self, app: App, id: str, bucket_args: dict, **kwargs):
        super().__init__(app, id, **kwargs)

        # kms key
        if not bucket_args['encryption']:
            bucket_key = Key(self, f"{id}Key",
                             description=f"Key used for {id} template",
                             alias=f"{id}Bucket",
                             enable_key_rotation=True,
                             removal_policy=RemovalPolicy.RETAIN)
            bucket_args["encryption_key"] = bucket_key
            bucket_args["encryption"] = BucketEncryption.KMS

        # bucket
        bucket_args["block_public_access"] = BlockPublicAccess.BLOCK_ALL
        bucket_args["versioned"] = True

        bucket = Bucket(self, f"{id}Bucket", **bucket_args)

        # bucket policy
        bucket.add_to_resource_policy(
            PolicyStatement(sid='AllowSSLRequestsOnly',
                            actions=['s3:*'],
                            effect=Effect.DENY,
                            resources=[
                                bucket.bucket_arn,
                                f"{bucket.bucket_arn}/*"
                            ],
                            conditions={
                                "Bool": {
                                    "aws:SecureTransport": "false"
                                }
                            },
                            principals=[AnyPrincipal()])
        )

        self.bucket = bucket
