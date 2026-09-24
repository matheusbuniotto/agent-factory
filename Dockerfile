# One image for local runs, ECS tasks and EC2. The container is the sandbox.
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git gh ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY factory ./factory
RUN uv sync --frozen --no-dev --extra logfire --extra aws
ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home factory \
 && git config --system --add safe.directory '*'
USER factory
RUN git config --global user.name "Agent Factory" \
 && git config --global user.email "agent-factory@users.noreply.github.com"

WORKDIR /work
ENTRYPOINT ["factory"]
CMD ["--help"]
