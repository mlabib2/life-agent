from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_user_id: int

    anthropic_api_key: str
    tavily_api_key: str
    openai_api_key: str = ""

    supabase_url: str
    supabase_service_key: str
    database_url: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    strava_client_id: str = ""
    strava_client_secret: str = ""

    apple_health_token: str = ""


settings = Settings()
