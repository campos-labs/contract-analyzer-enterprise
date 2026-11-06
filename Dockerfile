FROM python:3.14.4-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"
CMD ["contract-analyzer", "--help"]
