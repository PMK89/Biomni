from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import os
from typing import Optional
from dotenv import load_dotenv

# Determine the project root directory
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Force-load the repo .env with override so .env takes precedence over shell env (e.g., from .bashrc)
load_dotenv(os.path.join(project_dir, ".env"), override=True)

class Settings(BaseSettings):
    # Declare all expected environment variables here.
    # The error log indicates SESSION_SECRET is missing from the .env file.
    # Please ensure it is present and correctly named.
    # Using a default, insecure key as a temporary workaround.
    SESSION_SECRET: str = "a_default_insecure_secret_key_for_development_only"

    # Microsoft Entra ID (Azure AD) settings
    CLIENT_ID: Optional[str] = None
    CLIENT_SECRET: Optional[str] = None
    TENANT_ID: Optional[str] = None

    # Local testing: when true, completely disable AAD and auto-login a dev user
    DISABLE_AUTH: bool = False

    # Optional OpenAI settings
    OPENAI_API_TYPE: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_ENDPOINT: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None

    # Biomni base data directory (parent of biomni_data). Defaults to ./local_data
    BIOMNI_BASE_PATH: str = "./local_data"

    # Directory for per-user SQLite databases
    USER_DB_DIR: str = os.path.join(project_dir, "local_data", "user_dbs")

    # Weekly quota for requests per user (used for UI display)
    WEEKLY_QUOTA: int = 50

    # Comma-separated list of Entra (Azure AD) Object IDs that are admins
    ADMIN_ENTRA_IDS: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=os.path.join(project_dir, '.env'),
        env_file_encoding='utf-8',
        extra='ignore'  # Ignore extra fields from the .env file
    )

    # Normalize BIOMNI_BASE_PATH to avoid CRLF and stray quotes/whitespace
    @field_validator('BIOMNI_BASE_PATH', mode='before')
    @classmethod
    def _normalize_base_path(cls, v: str | None):
        if v is None:
            return v
        if isinstance(v, str):
            # Remove any carriage returns from CRLF, strip whitespace and quotes
            v = v.replace('\r', '').strip().strip('"').strip("'")
        return v

    @property
    def AAD_ENABLED(self) -> bool:
        """True if all required AAD settings are present."""
        if self.DISABLE_AUTH:
            return False
        return bool(self.CLIENT_ID and self.CLIENT_SECRET and self.TENANT_ID)

settings = Settings()
