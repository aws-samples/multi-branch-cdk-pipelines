import aws_cdk as cdk
import aws_cdk.aws_kms as kms
import jsii


@jsii.implements(cdk.IAspect)
class KeyRotationAspect:

  def visit(self, node):
    if isinstance(node, kms.CfnKey):
      node.enable_key_rotation = True
