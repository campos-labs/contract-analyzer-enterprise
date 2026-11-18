# Contract Analyzer Enterprise

Projeto para revisão rastreável de contratos B2B com decisões humanas. A base atual oferece inspeção local de DOCX e uma rota de saúde da API.

## Pré-requisitos

- Python 3.14 e [uv](https://docs.astral.sh/uv/) para execução local. O arquivo `.python-version` fixa a versão 3.14.4.
- Docker e Docker Compose para execução em container.

## Instalação local

Na raiz do projeto, instale as dependências e crie o ambiente virtual:

```bash
uv sync --locked
```

O comando instala o pacote da aplicação em modo editável e as dependências de desenvolvimento. A instalação usa o backend Hatchling e permite importar o pacote sem definir `PYTHONPATH`.

Para conferir se o arquivo de lock está atualizado em relação ao `pyproject.toml`:

```bash
uv lock --check
```

Para gerar a wheel e o sdist em `dist/`:

```bash
uv build --no-sources
```

## Configuração

Para usar o Docker Compose, crie o arquivo local de configuração a partir do exemplo:

```bash
cp .env.example .env
```

`APP_LOG_LEVEL` controla o nível de log da aplicação. Os valores aceitos são `DEBUG`, `INFO`, `WARNING` e `ERROR`; o padrão é `INFO`. Um valor inválido impede a inicialização. O nível configurado não altera os logs do Uvicorn. O arquivo `.env` é local e não deve ser versionado.

O Compose passa as variáveis de `.env` ao container. Na execução local, o código não carrega esse arquivo automaticamente: defina as variáveis no ambiente do processo, quando necessário.

## Execução local

Na raiz do projeto, inicie a aplicação:

```bash
uv run python main.py
```

Para escolher o nível de log localmente:

```bash
APP_LOG_LEVEL=DEBUG uv run python main.py
```

A execução local escuta apenas em `127.0.0.1:8000`. A documentação interativa do FastAPI estará em `http://127.0.0.1:8000/docs`.

## Execução com Docker Compose

Na raiz do projeto, construa a imagem e inicie o container:

```bash
docker compose up --build
```

O container executa a aplicação instalada com Uvicorn em `0.0.0.0:8000`. O Compose publica a porta 8000 apenas em `127.0.0.1` no host. Para encerrar, use `Ctrl+C` e execute:

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

## Inspeção local de DOCX

Na raiz do projeto, execute com as amostras sintéticas:

```bash
uv run python -m contract_analyzer_enterprise.documents tests/fixtures/docx/contract_reference.docx --anexo tests/fixtures/docx/related_reference.docx --storage .docx-inspection --output .docx-inspection/mapa.json
```

`--anexo` pode ser repetido. O relatório JSON registra papéis, revisões,
unidades, projeções, eventos e limitações. Os originais validados ficam
em `originals/<sha256>.docx` dentro do armazenamento indicado.
Cada objeto é publicado sem substituir um arquivo existente. Escolha
um caminho novo para cada relatório e use um volume local com suporte a
hard links. A pasta `.docx-inspection/` é ignorada pelo Git.

O mapa lê OOXML Transitional no corpo principal. Registra parágrafos,
títulos por nível de estrutura, tabelas, linhas e células físicas.
Mantém referências de numeração, espaços, tabs e quebras de texto.
As projeções separam inserções e exclusões textuais simples.
Comentários clássicos são eventos. Metadados modernos, movimentações,
revisões estruturais e outras construções fora do suporte são
inventariados. Tabelas mescladas e aninhadas recebem indicações de
limitação, preservando a ordem dos elementos físicos lidos.

As âncoras usam offsets Unicode de base zero, com fim exclusivo.
Cada intervalo vincula hash de revisão, parte, unidade e projeção aos
segmentos XML correspondentes. Projeções incompletas recusam âncoras.
Texto com `w:vanish` permanece no mapa. A projeção que o contém fica
incompleta quando a propriedade está ativa ou a visibilidade herdada
é incerta. O leitor considera os padrões do documento e os estilos
aplicáveis de parágrafo, caractere e tabela. Uma desativação direta
prevalece sobre a herança. A limitação indica o run e sua parte XML.
A cobertura do relatório se refere à leitura. Alteração, reconciliação
e clean ficam para os incrementos da jornada Word.

Os limites iniciais são 8 anexos, 32 MiB de entrada por DOCX, 64 MiB
de entrada somada, 2.048 entradas ZIP por pacote e até 250 mil nós
XML por inspeção. O pacote tem teto de 64 MiB expandidos e 32 MiB
por entrada. A ancoragem de comentários tem limite de 32 intervalos
simultâneos e 50 mil trechos projetados por documento. Conteúdo ativo,
como macros e objetos incorporados, é recusado. Links externos HTTP,
HTTPS e mailto são inventariados sem expor seus destinos. O comando
funciona offline.

## Testes e lint

```bash
uv run task test
```

A tarefa executa o lint e os testes com cobertura, gerando um relatório em `htmlcov/index.html`. Os testes cobrem a fundação HTTP e a ingestão, projeções e âncoras DOCX. Para executar apenas o lint:

```bash
uv run task lint
```

## Integração contínua

O workflow `CI` do GitHub Actions executa em pull requests para `main`, em pushes na `main` e manualmente pela aba Actions.

- **quality:** instala o Python definido em `.python-version`, o pacote e as dependências com `uv sync --locked --dev`, verifica a formatação, executa `task test` e constrói as distribuições Python. Também instala a wheel em ambiente isolado e importa a aplicação fora do checkout, sem `PYTHONPATH` e com configuração inválida para verificar que a importação não inicializa o serviço. O nome corresponde ao check exigido pela regra de proteção da branch `main`.
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
  A origem dos DOCX reutilizados está em [testes de inspeção](tests/fixtures/docx/README.md).

[Governança](https://github.com/campos-labs/.github/blob/main/CONTRIBUTING.md) ·
[Segurança](https://github.com/campos-labs/.github/blob/main/SECURITY.md) ·
[MIT](LICENSE)
