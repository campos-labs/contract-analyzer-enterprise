FROM python:3.14.4-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app

# Instala o uv usando a imagem oficial
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

# Instala dependências em uma camada separada
COPY pyproject.toml uv.lock .python-version ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# Copia o código e instala o pacote com as dependências de produção
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Inicia a aplicação instalada e recebe conexões pela rede do container
CMD ["uvicorn", "contract_analyzer_enterprise.app:app", "--host", "0.0.0.0", "--port", "8000"]
