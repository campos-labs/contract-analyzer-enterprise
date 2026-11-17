# Contract Analyzer Enterprise

Projeto para revisão rastreável de contratos B2B com decisões humanas. Atualmente, disponibiliza uma API FastAPI com uma rota de verificação de funcionamento.

## Pré-requisitos

- Python 3.14 ou superior e [uv](https://docs.astral.sh/uv/) para execução local. O arquivo `.python-version` fixa a versão 3.14.4.
- Docker e Docker Compose para execução em container.

## Instalação local

Na raiz do projeto, instale as dependências e crie o ambiente virtual:

```bash
uv sync --locked
```

O comando também instala as dependências de desenvolvimento. O código em `src/` não é instalado como pacote.

Para conferir se o arquivo de lock está atualizado em relação ao `pyproject.toml`:

```bash
uv lock --check
```

## Configuração

Para usar o Docker Compose, crie o arquivo local de configuração a partir do exemplo:

```bash
cp .env.example .env
```

`APP_LOG_LEVEL` controla o nível de log da aplicação. Os valores aceitos são `DEBUG`, `INFO`, `WARNING` e `ERROR`; o padrão é `INFO`. Um valor inválido impede a inicialização. O nível configurado não altera os logs do Uvicorn. O arquivo `.env` é local e não deve ser versionado.

O Compose passa as variáveis de `.env` ao container. Na execução local, o código não carrega esse arquivo automaticamente: defina as variáveis no ambiente do processo, quando necessário.

## Execução local

Na raiz do projeto, disponibilize `src/` para importação e inicie a aplicação:

```bash
PYTHONPATH=src uv run python main.py
```

Para escolher o nível de log localmente:

```bash
APP_LOG_LEVEL=DEBUG PYTHONPATH=src uv run python main.py
```

A API estará disponível em `http://127.0.0.1:8000`. A documentação interativa do FastAPI estará em `http://127.0.0.1:8000/docs`.

## Execução com Docker Compose

Na raiz do projeto, construa a imagem e inicie o container:

```bash
docker compose up --build
```

O Compose publica a porta 8000 apenas em `127.0.0.1` no host. Para encerrar, use `Ctrl+C` e execute:

```bash
docker compose down
```

Para consultar os logs da aplicação:

```bash
docker compose logs -f app
```

Após alterar `.env`, recrie o container para aplicar os novos valores:

```bash
docker compose up -d --force-recreate
```

## Verificação da API

Com a aplicação em execução, consulte a rota de saúde:

```bash
curl http://127.0.0.1:8000/healthz
```

A resposta esperada é `{"status":"ok"}`, com status HTTP 200. A rota verifica a resposta do processo HTTP; ela não consulta serviços externos.

## Testes e lint

```bash
uv run task test
```

A tarefa executa o lint e os testes com cobertura, gerando um relatório em `htmlcov/index.html`. Os testes verificam a rota de saúde e a configuração do nível de log. Para executar apenas o lint:

```bash
uv run task lint
```
