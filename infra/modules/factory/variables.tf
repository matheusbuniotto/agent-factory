variable "name" {
  description = "Prefix for every resource."
  type        = string
  default     = "factory"
}

# Network: an existing VPC with private subnets and no internet route.

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets for the workers, the UI, the Lambdas and EFS. One is enough."
  type        = list(string)
}

variable "route_table_ids" {
  description = "Route tables of those subnets, for the free S3 gateway endpoint."
  type        = list(string)
  default     = []
}

variable "endpoints" {
  description = "Interface endpoints to create. Leave out the ones your VPC already has; [] creates none."
  type        = list(string)
  default     = ["bedrock-runtime", "ecr.api", "ecr.dkr", "ecs", "logs", "secretsmanager", "sqs", "sts", "ssmmessages"]
}

variable "https_proxy" {
  description = "Egress proxy to GitHub and Jira, e.g. http://proxy.corp:3128. Empty when a NAT allow-list handles it."
  type        = string
  default     = ""
}

# Jira

variable "projects" {
  description = "Jira project key to the GitHub repo its tickets change."
  type        = map(string)
  # { PROJ = "acme/api" }
}

variable "jira" {
  description = "Trigger label and the statuses a ticket moves through."
  type = object({
    trigger = optional(string, "factory")
    ready   = optional(string, "Ready for agent")
    started = optional(string, "In Progress")
    done    = optional(string, "In Review")
  })
  default = {}
}

variable "poll_minutes" {
  type    = number
  default = 2
}

# GitHub

variable "github_host" {
  description = "github.com, or your GitHub Enterprise Server host."
  type        = string
  default     = "github.com"
}

variable "github_api" {
  description = "https://api.github.com, or https://<host>/api/v3 on Enterprise Server."
  type        = string
  default     = "https://api.github.com"
}

# Workers

variable "image" {
  description = "Worker and UI image. Defaults to the ECR repository this module creates, tag latest."
  type        = string
  default     = null
}

variable "settings" {
  description = "A factory.toml layered over every repo's own (models, limits, human points)."
  type        = string
  default     = <<-TOML
    runtime = "pydantic-ai"

    [models]   # check what your account can use: aws bedrock list-inference-profiles
    planner     = "bedrock:us.anthropic.claude-opus-4-5-20251101-v1:0"
    implementer = "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    reviewer    = "bedrock:us.anthropic.claude-opus-4-5-20251101-v1:0"
    scribe      = "bedrock:us.anthropic.claude-haiku-4-5-20251001-v1:0"

    [human]
    channel = "inbox"

    [limits]
    searches = 0   # no web search from a closed VPC
  TOML
}

variable "worker" {
  type = object({
    cpu          = optional(number, 1024)
    memory       = optional(number, 4096)
    architecture = optional(string, "X86_64")
    spot         = optional(bool, true)
    timeout      = optional(string, "3h")
  })
  default = {}
}

variable "environment" {
  description = "Extra environment for the workers and the UI."
  type        = map(string)
  default     = {}
}

# UI

variable "ui" {
  description = "Run the dashboard. Reach it with `make ui` (SSM port forwarding), or set `alb` for a team."
  type        = bool
  default     = true
}

variable "alb" {
  description = "An internal load balancer with single sign-on in front of the UI. null for none."
  type = object({
    certificate_arn        = string
    allowed_cidrs          = list(string)
    issuer                 = string
    authorization_endpoint = string
    token_endpoint         = string
    user_info_endpoint     = string
    client_id              = string
    client_secret          = string
  })
  default   = null
  sensitive = true
}

variable "ui_url" {
  description = "Where people open the UI, for links in Jira comments. Empty for none."
  type        = string
  default     = ""
}

# Spend

variable "budget" {
  description = "Monthly budget in USD, emailed at 80% and 100%. null for none."
  type = object({
    limit  = number
    emails = list(string)
  })
  default = null
}

variable "log_days" {
  type    = number
  default = 30
}
