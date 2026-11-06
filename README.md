# Contract Analyzer Enterprise

Base do produto para revisão rastreável de contratos B2B. A arquitetura da
v1.0 está em [DESIGN.md](DESIGN.md); o motor de revisão ainda será implementado.

## Disponível

Pacote instalável, CLI de identificação/ajuda, ferramentas de qualidade e imagem
Docker para verificar o empacotamento. Não há API, portal, análise DOCX, Writer,
fila ou chamadas ao LLM implementados neste bootstrap. `0.0.0` identifica esta
base de desenvolvimento; não existe release ou protótipo publicado.

## Desenvolvimento

Python **3.14.4** (gerenciado pelo uv) e uv **0.12.7**. Docker é opcional.

```bash
uv sync --locked
uv run --no-sync contract-analyzer --version
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
```

```bash
docker compose config --quiet
docker compose build
docker compose run --rm bootstrap
```

O container executa apenas a identificação do pacote e encerra. Não publica
porta nem inicia serviços fictícios. `.env.example` não exige segredos.
A suíte de testes funcionais acompanhará a implementação; o CI atual verifica
qualidade, build e instalação do wheel em ambiente isolado.

## Origem e próximos passos

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

Fundação técnica, testes e fluxos funcionais serão entregues nas issues da v1.0.
MCP, conectores e RAG histórico permanecem na Epic, sem antecipação de escopo.

[Governança](https://github.com/campos-labs/.github/blob/main/CONTRIBUTING.md) ·
[Segurança](https://github.com/campos-labs/.github/blob/main/SECURITY.md) ·
[MIT](LICENSE)
