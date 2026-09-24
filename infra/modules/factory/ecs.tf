# One Fargate task per ticket, and the dashboard as a small always-on service.

locals {
  image = coalesce(var.image, "${aws_ecr_repository.factory.repository_url}:latest")

  proxy = var.https_proxy == "" ? {} : {
    HTTPS_PROXY = var.https_proxy
    NO_PROXY    = ".amazonaws.com,169.254.169.254,169.254.170.2"
  }

  environment = merge(local.proxy, var.environment, {
    FACTORY_HOME = "/factory"
    AWS_REGION   = data.aws_region.current.region
  })
}

resource "aws_ecs_cluster" "factory" {
  name = var.name
}

resource "aws_ecs_cluster_capacity_providers" "factory" {
  cluster_name       = aws_ecs_cluster.factory.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker.cpu
  memory                   = var.worker.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.worker.architecture
  }

  volume {
    name = "runs"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.runs.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.runs.id
      }
    }
  }

  container_definitions = jsonencode([{
    name       = "worker"
    image      = local.image
    essential  = true
    entryPoint = ["factory-ticket"]
    environment = [for key, value in merge(local.environment, {
      GH_HOST            = var.github_host
      FACTORY_SETTINGS   = var.settings
      FACTORY_REPORT_URL = aws_sqs_queue.results.url
      FACTORY_TIMEOUT    = var.worker.timeout
    }) : { name = key, value = value }]
    mountPoints = [{ sourceVolume = "runs", containerPath = "/factory" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.factory.name
        awslogs-region        = data.aws_region.current.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "ui" {
  count = var.ui ? 1 : 0

  family                   = "${var.name}-ui"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.ui.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.worker.architecture
  }

  volume {
    name = "runs"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.runs.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.runs.id
      }
    }
  }

  container_definitions = jsonencode([{
    name         = "ui"
    image        = local.image
    essential    = true
    command      = ["ui", "--host", "0.0.0.0", "--port", "8765", "--repo", "/tmp"]
    environment  = [for key, value in local.environment : { name = key, value = value }]
    portMappings = [{ containerPort = 8765 }]
    mountPoints  = [{ sourceVolume = "runs", containerPath = "/factory" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.factory.name
        awslogs-region        = data.aws_region.current.region
        awslogs-stream-prefix = "ui"
      }
    }
  }])
}

resource "aws_ecs_service" "ui" {
  count = var.ui ? 1 : 0

  name                   = "${var.name}-ui"
  cluster                = aws_ecs_cluster.factory.id
  task_definition        = aws_ecs_task_definition.ui[0].arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true # SSM port forwarding: `make ui`

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = concat([aws_security_group.worker.id], aws_security_group.ui[*].id)
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = range(local.alb)
    content {
      target_group_arn = aws_lb_target_group.ui[0].arn
      container_name   = "ui"
      container_port   = 8765
    }
  }
}
