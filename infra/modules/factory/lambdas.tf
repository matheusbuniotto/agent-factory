# poll: Jira → one ECS task per ready ticket, every few minutes.
# notify: a run's outcome (or a worker that died) → a Jira comment.
# `make lambdas` builds ../../build/lambdas: the handlers plus PyJWT.

data "archive_file" "lambdas" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/lambdas"
  output_path = "${path.module}/../../build/lambdas.zip"
}

locals {
  lambda = {
    runtime       = "python3.13"
    architectures = ["arm64"]
    environment   = merge(local.proxy, { JIRA_SECRET = aws_secretsmanager_secret.jira.arn })
  }
}

resource "aws_lambda_function" "poll" {
  function_name    = "${var.name}-poll"
  role             = aws_iam_role.poll.arn
  handler          = "poll.handler"
  runtime          = local.lambda.runtime
  architectures    = local.lambda.architectures
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 60

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.worker.id]
  }

  environment {
    variables = merge(local.lambda.environment, {
      GITHUB_SECRET   = aws_secretsmanager_secret.github.arn
      GITHUB_API      = var.github_api
      PROJECTS        = jsonencode(var.projects)
      TRIGGER         = var.jira.trigger
      READY_STATUS    = var.jira.ready
      STARTED_STATUS  = var.jira.started
      CLUSTER         = aws_ecs_cluster.factory.arn
      TASK_DEFINITION = aws_ecs_task_definition.worker.arn
      CAPACITY        = var.worker.spot ? "FARGATE_SPOT" : "FARGATE"
      SUBNETS         = join(",", var.subnet_ids)
      SECURITY_GROUP  = aws_security_group.worker.id
    })
  }

  depends_on = [aws_cloudwatch_log_group.poll]
}

resource "aws_lambda_function" "notify" {
  function_name    = "${var.name}-notify"
  role             = aws_iam_role.notify.arn
  handler          = "notify.handler"
  runtime          = local.lambda.runtime
  architectures    = local.lambda.architectures
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 60

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.worker.id]
  }

  environment {
    variables = merge(local.lambda.environment, {
      DONE_STATUS = var.jira.done
      UI_URL      = var.ui_url
    })
  }

  depends_on = [aws_cloudwatch_log_group.notify]
}

resource "aws_cloudwatch_log_group" "poll" {
  name              = "/aws/lambda/${var.name}-poll"
  retention_in_days = var.log_days
}

resource "aws_cloudwatch_log_group" "notify" {
  name              = "/aws/lambda/${var.name}-notify"
  retention_in_days = var.log_days
}

resource "aws_scheduler_schedule" "poll" {
  name                = "${var.name}-poll"
  schedule_expression = "rate(${var.poll_minutes} minutes)"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.poll.arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 0 # the next poll is the retry
    }
  }
}

resource "aws_lambda_event_source_mapping" "results" {
  event_source_arn = aws_sqs_queue.results.arn
  function_name    = aws_lambda_function.notify.arn
  batch_size       = 1
}

resource "aws_cloudwatch_event_rule" "worker_stopped" {
  name        = "${var.name}-worker-stopped"
  description = "A worker task stopped; notify reports it if the run could not"
  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn        = [aws_ecs_cluster.factory.arn]
      lastStatus        = ["STOPPED"]
      taskDefinitionArn = [{ prefix = "arn:aws:ecs:${data.aws_region.current.region}:${local.account}:task-definition/${aws_ecs_task_definition.worker.family}:" }]
    }
  })
}

resource "aws_cloudwatch_event_target" "worker_stopped" {
  rule = aws_cloudwatch_event_rule.worker_stopped.name
  arn  = aws_lambda_function.notify.arn
}

resource "aws_lambda_permission" "worker_stopped" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notify.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.worker_stopped.arn
}
