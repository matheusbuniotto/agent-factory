# The whole factory on floci (https://floci.io), with fake.py standing in for
# Jira and GitHub. `make local` from infra/ runs it all.

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  s3_use_path_style           = true
  # every service at AWS_ENDPOINT_URL, set by the Makefile
}

locals {
  fake = "http://host.docker.internal:9000" # fake.py, seen from floci's containers
}

resource "aws_vpc" "closed" {
  cidr_block = "10.42.0.0/16"
}

resource "aws_subnet" "private" {
  vpc_id     = aws_vpc.closed.id
  cidr_block = "10.42.1.0/24"
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.closed.id
}

module "factory" {
  source = "../modules/factory"

  vpc_id          = aws_vpc.closed.id
  subnet_ids      = [aws_subnet.private.id]
  route_table_ids = [aws_route_table.private.id]
  projects        = { PROJ = "acme/calc" }
  github_api      = local.fake
  image           = "agent-factory:latest"
  worker          = { spot = false, architecture = "ARM64" }
  environment = {
    AWS_ENDPOINT_URL = "http://host.docker.internal:4566" # floci, from inside a worker
    FACTORY_GIT_URL  = local.fake
  }
}

resource "tls_private_key" "github_app" {
  algorithm = "RSA"
}

resource "aws_secretsmanager_secret_version" "jira" {
  secret_id     = module.factory.secrets.jira
  secret_string = jsonencode({ site = local.fake, email = "bot@example.com", token = "fake" })
}

resource "aws_secretsmanager_secret_version" "github" {
  secret_id = module.factory.secrets.github
  secret_string = jsonencode({
    app_id          = "1"
    installation_id = "1"
    private_key     = tls_private_key.github_app.private_key_pem
  })
}

output "factory" {
  value = module.factory
}
