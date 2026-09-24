"""Secrets Manager, where the Lambdas keep the Jira and GitHub App credentials."""

import boto3


def secret(arn: str) -> str:
    return boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
