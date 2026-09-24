# Run folders on EFS, the results queue, the image repository and the secrets.

resource "aws_efs_file_system" "runs" {
  creation_token = "${var.name}-runs"
  encrypted      = true

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = { Name = "${var.name}-runs" }
}

resource "aws_efs_mount_target" "runs" {
  count = length(var.subnet_ids)

  file_system_id  = aws_efs_file_system.runs.id
  subnet_id       = var.subnet_ids[count.index]
  security_groups = [aws_security_group.endpoints.id]
}

resource "aws_efs_access_point" "runs" {
  file_system_id = aws_efs_file_system.runs.id

  posix_user { # the image's `factory` user
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/factory"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "750"
    }
  }
}

resource "aws_sqs_queue" "results_dead" {
  name                      = "${var.name}-results-dead"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "results" {
  name                       = "${var.name}-results"
  visibility_timeout_seconds = 120
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.results_dead.arn
    maxReceiveCount     = 5
  })
}

resource "aws_ecr_repository" "factory" {
  name                 = var.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_secretsmanager_secret" "jira" {
  name        = "${var.name}/jira"
  description = <<-EOT
    {"site": "https://acme.atlassian.net", "email": "bot@acme.com", "token": "..."} (no email on Data Center)
  EOT
}

resource "aws_secretsmanager_secret" "github" {
  name        = "${var.name}/github-app"
  description = <<-EOT
    {"app_id": "...", "installation_id": "...", "private_key": "-----BEGIN RSA PRIVATE KEY-----..."}
  EOT
}

resource "aws_cloudwatch_log_group" "factory" {
  name              = "/${var.name}"
  retention_in_days = var.log_days
}
