# Optional: an internal load balancer that signs people in through your identity
# provider (Okta, Entra, Google) before they reach the dashboard. The UI has no
# login of its own, so it must never be public.

locals {
  alb = nonsensitive(var.alb != null) ? 1 : 0 # the client secret makes the whole object sensitive
}

resource "aws_security_group" "alb" {
  count = local.alb

  name        = "${var.name}-alb"
  description = "HTTPS from the corporate network to the UI"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.alb.allowed_cidrs
  }

  egress {
    description = "The identity provider, and the UI"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ui" {
  count = local.alb

  name        = "${var.name}-ui"
  description = "The UI, reachable from its load balancer only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8765
    to_port         = 8765
    protocol        = "tcp"
    security_groups = [aws_security_group.alb[0].id]
  }
}

resource "aws_lb" "ui" {
  count = local.alb

  name               = "${var.name}-ui"
  internal           = true
  load_balancer_type = "application"
  subnets            = var.subnet_ids
  security_groups    = [aws_security_group.alb[0].id]
}

resource "aws_lb_target_group" "ui" {
  count = local.alb

  name        = "${var.name}-ui"
  port        = 8765
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    path = "/"
  }
}

resource "aws_lb_listener" "ui" {
  count = local.alb

  load_balancer_arn = aws_lb.ui[0].arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.alb.certificate_arn

  default_action {
    type  = "authenticate-oidc"
    order = 1
    authenticate_oidc {
      issuer                 = var.alb.issuer
      authorization_endpoint = var.alb.authorization_endpoint
      token_endpoint         = var.alb.token_endpoint
      user_info_endpoint     = var.alb.user_info_endpoint
      client_id              = var.alb.client_id
      client_secret          = var.alb.client_secret
    }
  }

  default_action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.ui[0].arn
  }
}

# Spend alarm: tokens are the real cost.

resource "aws_budgets_budget" "factory" {
  count = var.budget == null ? 0 : 1

  name         = var.name
  budget_type  = "COST"
  limit_amount = var.budget.limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget.emails
    }
  }
}
