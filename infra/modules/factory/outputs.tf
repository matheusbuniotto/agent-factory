output "repository_url" {
  description = "Push the factory image here."
  value       = aws_ecr_repository.factory.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.factory.name
}

output "ui_service" {
  value = var.ui ? aws_ecs_service.ui[0].name : null
}

output "ui_alb" {
  description = "Internal DNS name of the UI load balancer."
  value       = one(aws_lb.ui[*].dns_name)
}

output "secrets" {
  description = "Fill these in once: make secrets."
  value = {
    jira   = aws_secretsmanager_secret.jira.name
    github = aws_secretsmanager_secret.github.name
  }
}

output "results_queue" {
  value = aws_sqs_queue.results.url
}

output "poll_function" {
  value = aws_lambda_function.poll.function_name
}
