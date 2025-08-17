import boto3, logging
def log_aws_identity():
    sts = boto3.client("sts")
    who = sts.get_caller_identity()
    print(f"AWS Identity: {who}")
log_aws_identity()
