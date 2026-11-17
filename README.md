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

## Integração contínua

O workflow `CI` do GitHub Actions executa em pull requests para `main`, em pushes na `main` e manualmente pela aba Actions.

- **quality:** instala o Python definido em `.python-version` e as dependências com `uv sync --locked --dev`, verifica a formatação e executa `task test`. O nome corresponde ao check exigido pela regra de proteção da branch `main`.
- **Docker e health check:** utiliza `.env.example`, valida o Compose, constrói e inicia o container e verifica a resposta de `GET /healthz` pela porta publicada no host.

## Origem e arquitetura

A arquitetura da v1.0 está em [DESIGN.md](DESIGN.md).

- [RFC #62](https://github.com/campos-labs/project-hub/issues/62),
  [ADR #110](https://github.com/campos-labs/project-hub/issues/110) e
  [DESIGN aprovado](https://github.com/campos-labs/project-hub/pull/111).
- [Bootstrap #1](https://github.com/campos-labs/contract-analyzer-enterprise/issues/1)
  e [evolução 1.x #2](https://github.com/campos-labs/contract-analyzer-enterprise/issues/2).
- Template [python-project-template](https://github.com/campos-labs/python-project-template),
  referência gerada `251fdadf2368c3748e47c39b58f7fceda95a5c30`.
- POC, spike, fixtures e evidências permanecem no
  [project-hub](https://github.com/campos-labs/project-hub/tree/6c301455fce7a182a044ea5f44bba88e8f6731c2/docs/rfcs/006-contract-analyser-enterprise/research).
  Fixtures serão promovidas seletivamente junto aos primeiros consumidores e
  testes; os scripts experimentais não são a aplicação.

[Governança](https://github.com/campos-labs/.github/blob/main/CONTRIBUTING.md) ·
[Segurança](https://github.com/campos-labs/.github/blob/main/SECURITY.md) ·
[MIT](LICENSE)
