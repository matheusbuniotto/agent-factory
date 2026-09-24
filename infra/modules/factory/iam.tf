# Least privilege. The worker runs code an agent wrote from an untrusted ticket,
# so it can call Bedrock and report its result, and nothing else.

data "aws_caller_identity" "current" {}

locals {
  account = data.aws_caller_identity.current.account_id
  trust = {
    ecs       = "ecs-tasks.amazonaws.com"
    lambda    = "lambda.amazonaws.com"
    scheduler = "scheduler.amazonaws.com"
  }
}

data "aws_iam_policy_document" "trust" {
  for_each = local.trust

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = [each.value]
    }
  }
}

# ECS pulls the image and ships logs.

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.trust["ecs"].json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The worker: Bedrock and the results queue.

resource "aws_iam_role" "worker" {
  name               = "${var.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.trust["ecs"].json
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "Models"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:*::foundation-model/anthropic.*", "arn:aws:bedrock:*:${local.account}:inference-profile/*"]
  }

  statement {
    sid       = "Report"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.results.arn]
  }
}

resource "aws_iam_role_policy" "worker" {
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

# The UI: only the SSM channel for port forwarding.

resource "aws_iam_role" "ui" {
  name               = "${var.name}-ui"
  assume_role_policy = data.aws_iam_policy_document.trust["ecs"].json
}

data "aws_iam_policy_document" "ui" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ui" {
  role   = aws_iam_role.ui.id
  policy = data.aws_iam_policy_document.ui.json
}

# The poller: reads both secrets and starts worker tasks.

resource "aws_iam_role" "poll" {
  name               = "${var.name}-poll"
  assume_role_policy = data.aws_iam_policy_document.trust["lambda"].json
}

data "aws_iam_policy_document" "poll" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.jira.arn, aws_secretsmanager_secret.github.arn]
  }

  statement {
    actions   = ["ecs:RunTask"]
    resources = ["arn:aws:ecs:${data.aws_region.current.region}:${local.account}:task-definition/${aws_ecs_task_definition.worker.family}:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.factory.arn]
    }
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.worker.arn]
  }
}

resource "aws_iam_role_policy" "poll" {
  role   = aws_iam_role.poll.id
  policy = data.aws_iam_policy_document.poll.json
}

# The notifier: reads the Jira secret and the results queue.

resource "aws_iam_role" "notify" {
  name               = "${var.name}-notify"
  assume_role_policy = data.aws_iam_policy_document.trust["lambda"].json
}

data "aws_iam_policy_document" "notify" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.jira.arn]
  }

  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.results.arn]
  }
}

resource "aws_iam_role_policy" "notify" {
  role   = aws_iam_role.notify.id
  policy = data.aws_iam_policy_document.notify.json
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  for_each = { poll = aws_iam_role.poll.name, notify = aws_iam_role.notify.name }

  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# The schedule that wakes the poller.

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.trust["scheduler"].json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.poll.arn }]
  })
}
