FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app

# Instala o uv usando a imagem oficial
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# Instala dependências em uma camada separada
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# Copia o código e sincroniza as dependências de produção
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Inicia a aplicação pelo ponto de entrada
CMD ["uv", "run", "--no-sync", "python", "main.py"]
