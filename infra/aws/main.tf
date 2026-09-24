# The factory in your AWS account, inside an existing closed VPC.
# Copy terraform.tfvars.example to terraform.tfvars, then `make deploy` from infra/.

terraform {
  # Keep state in S3 once more than one person deploys:
  # backend "s3" {
  #   bucket       = "acme-terraform-state"
  #   key          = "agent-factory/terraform.tfstate"
  #   region       = "us-east-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { app = "agent-factory" }
  }
}

module "factory" {
  source = "../modules/factory"

  vpc_id          = var.vpc_id
  subnet_ids      = var.subnet_ids
  route_table_ids = var.route_table_ids
  endpoints       = var.endpoints
  https_proxy     = var.https_proxy
  projects        = var.projects
  jira            = var.jira
  github_host     = var.github_host
  github_api      = var.github_api
  alb             = var.alb
  ui_url          = var.ui_url
  budget          = var.budget
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "route_table_ids" {
  type    = list(string)
  default = []
}

variable "endpoints" {
  type    = list(string)
  default = ["bedrock-runtime", "ecr.api", "ecr.dkr", "ecs", "logs", "secretsmanager", "sqs", "sts", "ssmmessages"]
}

variable "https_proxy" {
  type    = string
  default = ""
}

variable "projects" {
  type = map(string)
}

variable "jira" {
  type    = any
  default = {}
}

variable "github_host" {
  type    = string
  default = "github.com"
}

variable "github_api" {
  type    = string
  default = "https://api.github.com"
}

variable "alb" {
  type      = any
  default   = null
  sensitive = true
}

variable "ui_url" {
  type    = string
  default = ""
}

variable "budget" {
  type    = any
  default = null
}

output "factory" {
  value = module.factory
}
