"""
Biomni Configuration Management

Simple configuration class for centralizing common settings.
Maintains full backward compatibility with existing code.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Load the project-root .env with override so it takes precedence over shell env
_here = os.path.dirname(__file__)
_project_root = os.path.abspath(os.path.join(_here, "..", ".."))
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)


@dataclass
class BiomniConfig:
    """Central configuration for Biomni agent.

    All settings are optional and have sensible defaults.
    API keys are still read from environment variables to maintain
    compatibility with existing .env file structure.

    Usage:
        # Create config with defaults
        config = BiomniConfig()

        # Override specific settings
        config = BiomniConfig(llm="gpt-4", timeout_seconds=1200)

        # Modify after creation
        config.path = "./custom_data"
    """

    # Data and execution settings
    path: str = "./local_data"
    timeout_seconds: int = 600

    # LLM settings (API keys still from environment)
    llm: str = "gpt-5"
    temperature: float = 1.0

    # Tool settings
    use_tool_retriever: bool = True

    # Custom model settings (for custom LLM serving)
    base_url: str | None = None
    api_key: str | None = os.getenv("OPENAI_API_KEY")  # Only for custom models, not provider API keys

    # LLM source (auto-detected if None)
    source: str | None = None

    def __post_init__(self):
        """Load any environment variable overrides if they exist."""
        # Check for environment variable overrides (optional)
        # Support both old and new names for backwards compatibility
        if os.getenv("BIOMNI_PATH") or os.getenv("BIOMNI_DATA_PATH"):
            self.path = os.getenv("BIOMNI_PATH") or os.getenv("BIOMNI_DATA_PATH")
        if os.getenv("BIOMNI_TIMEOUT_SECONDS"):
            self.timeout_seconds = int(os.getenv("BIOMNI_TIMEOUT_SECONDS"))
        if os.getenv("BIOMNI_LLM") or os.getenv("BIOMNI_LLM_MODEL"):
            self.llm = os.getenv("BIOMNI_LLM") or os.getenv("BIOMNI_LLM_MODEL")
        if os.getenv("BIOMNI_USE_TOOL_RETRIEVER"):
            self.use_tool_retriever = os.getenv("BIOMNI_USE_TOOL_RETRIEVER").lower() == "true"
        if os.getenv("BIOMNI_TEMPERATURE"):
            self.temperature = float(os.getenv("BIOMNI_TEMPERATURE"))
        if os.getenv("BIOMNI_CUSTOM_BASE_URL"):
            self.base_url = os.getenv("BIOMNI_CUSTOM_BASE_URL")

        # Resolve API key precedence:
        # - Use OPENAI_API_KEY by default
        # - If a custom model is configured (custom base_url or source==Custom), allow BIOMNI_CUSTOM_API_KEY to override
        openai_key = os.getenv("OPENAI_API_KEY")
        custom_key = os.getenv("BIOMNI_CUSTOM_API_KEY")
        source_env = os.getenv("BIOMNI_SOURCE") or self.source
        is_custom = bool(self.base_url) or (str(source_env).lower() == "custom" if source_env else False)
        if is_custom:
            self.api_key = custom_key or openai_key or self.api_key
        else:
            self.api_key = openai_key or self.api_key
        if os.getenv("BIOMNI_SOURCE"):
            self.source = os.getenv("BIOMNI_SOURCE")

    def to_dict(self) -> dict:
        """Convert config to dictionary for easy access."""
        return {
            "path": self.path,
            "timeout_seconds": self.timeout_seconds,
            "llm": self.llm,
            "temperature": self.temperature,
            "use_tool_retriever": self.use_tool_retriever,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "source": self.source,
        }


# Global default config instance (optional, for convenience)
default_config = BiomniConfig()
