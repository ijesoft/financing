from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureFlags(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    banking_grade_mode: bool = False
    banking_grade_frontend: bool = False


flags = FeatureFlags()
