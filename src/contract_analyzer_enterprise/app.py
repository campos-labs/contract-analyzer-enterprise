import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from contract_analyzer_enterprise.settings import Settings

logger = logging.getLogger('contract_analyzer_enterprise')


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                '%(asctime)s %(levelname)s %(name)s: %(message)s'
            )
        )
        logger.addHandler(handler)

    logger.setLevel(settings.log_level)
    logger.propagate = False

    logger.info('Aplicação iniciada')

    try:
        yield
    finally:
        logger.info('Aplicação encerrada')


app = FastAPI(
    title='Contract Analyzer Enterprise',
    description='Revisão rastreável de contratos B2B com decisões humanas.',
    version='0.1.0',
    contact={'name': 'Campos Labs'},
    lifespan=lifespan,
)


@app.get('/healthz', tags=['Healthz'])
async def healthz_check():
    return {'status': 'ok'}
