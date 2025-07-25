from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Optional

# Determine the project root directory
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    # Declare all expected environment variables here.
    # The error log indicates SESSION_SECRET is missing from the .env file.
    # Please ensure it is present and correctly named.
    # Using a default, insecure key as a temporary workaround.
    SESSION_SECRET: str = "a_default_insecure_secret_key_for_development_only"

    # Microsoft Entra ID (Azure AD) settings - These are placeholders!
    # Please provide real values in your .env file for authentication to work.
    CLIENT_ID: str = "placeholder_client_id"
    CLIENT_SECRET: str = "placeholder_client_secret"
    TENANT_ID: str = "placeholder_tenant_id"

    # Optional OpenAI settings
    OPENAI_API_TYPE: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_ENDPOINT: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=os.path.join(project_dir, '.env'),
        env_file_encoding='utf-8',
        extra='ignore'  # Ignore extra fields from the .env file
    )

settings = Settings()
