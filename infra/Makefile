# The factory on AWS. From this folder:
#
#   make local                     everything on floci, with fake Jira and GitHub
#   make deploy                    the real thing (fill aws/terraform.tfvars first)
#   make secrets JIRA=jira.json GITHUB=github.json
#   make ui                        the dashboard on http://localhost:8765, over SSM

LAMBDAS   := build/lambdas
FLOCI     := AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1
AWS_TF    := terraform -chdir=aws
OUTPUT     = $(shell $(AWS_TF) output -json factory | python3 -c "import json,sys; print(json.load(sys.stdin)['$(1)'])")
PLATFORM  ?= linux/amd64

.PHONY: lambdas image local local-down poll deploy push secrets ui destroy

lambdas:  ## the Lambda handlers plus PyJWT, for arm64
	rm -rf $(LAMBDAS) && mkdir -p $(LAMBDAS)
	cp lambdas/*.py $(LAMBDAS)/
	uv pip install --quiet --target $(LAMBDAS) --python-version 3.13 \
		--python-platform aarch64-manylinux2014 --only-binary :all: -r lambdas/requirements.txt

image:
	docker build --platform $(PLATFORM) -t agent-factory:latest ..

# Local: floci plays AWS, fake.py plays Jira and GitHub.

local: PLATFORM = linux/arm64
local: lambdas image
	floci start
	terraform -chdir=local init -input=false -upgrade
	$(FLOCI) terraform -chdir=local apply -input=false -auto-approve
	@echo "\nNow: python local/fake.py   (another terminal), then: make poll"

poll:  ## run the poller once instead of waiting for the schedule
	$(FLOCI) aws lambda invoke --function-name factory-poll /dev/stdout

local-down:  ## floci keeps nothing once stopped, so there is nothing to destroy
	floci stop
	rm -f local/terraform.tfstate*

# AWS

deploy: lambdas
	$(AWS_TF) init -input=false
	$(AWS_TF) apply -input=false
	$(MAKE) push

push: image
	aws ecr get-login-password | docker login --username AWS --password-stdin $(firstword $(subst /, ,$(call OUTPUT,repository_url)))
	docker tag agent-factory:latest $(call OUTPUT,repository_url):latest
	docker push $(call OUTPUT,repository_url):latest

secrets:  ## JIRA and GITHUB are JSON files; see the secret descriptions for their shape
	aws secretsmanager put-secret-value --secret-id factory/jira --secret-string file://$(JIRA)
	aws secretsmanager put-secret-value --secret-id factory/github-app --secret-string file://$(GITHUB)

ui:  ## needs the Session Manager plugin for the AWS CLI
	@task=$$(aws ecs list-tasks --cluster factory --service-name factory-ui --query 'taskArns[0]' --output text); \
	runtime=$$(aws ecs describe-tasks --cluster factory --tasks $$task \
		--query 'tasks[0].containers[0].runtimeId' --output text); \
	aws ssm start-session --target "ecs:factory_$${task##*/}_$$runtime" \
		--document-name AWS-StartPortForwardingSession --parameters portNumber=8765,localPortNumber=8765

destroy:
	$(AWS_TF) destroy
