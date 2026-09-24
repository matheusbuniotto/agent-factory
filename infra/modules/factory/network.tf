# Security groups and the VPC endpoints that stand in for the internet.

data "aws_region" "current" {}

data "aws_vpc" "this" {
  id = var.vpc_id
}

resource "aws_security_group" "worker" {
  name        = "${var.name}-worker"
  description = "Workers, UI and Lambdas: HTTPS out, nothing in"
  vpc_id      = var.vpc_id

  egress {
    description = "VPC endpoints, and GitHub and Jira through the proxy"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "EFS and the proxy inside the VPC"
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.this.cidr_block]
  }
}

resource "aws_security_group" "endpoints" {
  name        = "${var.name}-endpoints"
  description = "VPC endpoints and EFS, reachable from the factory only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(var.endpoints)

  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "s3" {
  count = length(var.route_table_ids) > 0 ? 1 : 0

  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids
}
