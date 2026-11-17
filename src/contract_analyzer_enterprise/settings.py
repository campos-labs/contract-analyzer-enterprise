from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')

    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
