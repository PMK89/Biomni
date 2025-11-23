"""Extension plumbing used by the integration branch."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

import logging

LOGGER = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path("config/esqlabs_agent_config.yaml")


def _read_config_file(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is an optional dependency
        LOGGER.warning("PyYAML is not installed; skipping ESQlabs extension config at %s", path)
        return {}

    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
            if not isinstance(data, dict):
                LOGGER.warning("Extension config %s must contain a mapping, got %s", path, type(data))
                return {}
            return data
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Unable to read extension config %s: %s", path, exc)
        return {}


def load_extension_config() -> dict[str, Any]:
    """Load extension config from BIOMNI_AGENT_CONFIG or the default path."""

    override = os.getenv("BIOMNI_AGENT_CONFIG")
    if override:
        return _read_config_file(Path(override))
    if _DEFAULT_CONFIG.exists():
        return _read_config_file(_DEFAULT_CONFIG)
    return {}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _merge_env_descriptors(agent, enable: bool, extra_data: dict[str, str] | None, extra_libs: dict[str, str] | None):
    if not enable or (not extra_data and not extra_libs):
        return
    if not extra_data and not extra_libs:
        return
    try:
        from biomni import env_desc
    except Exception:  # pragma: no cover - best effort
        LOGGER.debug("Unable to import env_desc for ESQlabs merge", exc_info=True)
        env_desc = None
    if env_desc:
        env_desc.merge_additional_descriptors(extra_data, extra_libs)  # type: ignore[attr-defined]
    if extra_data and hasattr(agent, "data_lake_dict"):
        agent.data_lake_dict.update(extra_data)
    if extra_libs and hasattr(agent, "library_content_dict"):
        agent.library_content_dict.update(extra_libs)


def _normalize_namespaces(value: Any) -> Sequence[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    try:
        return [str(v) for v in list(value)]
    except Exception:  # noqa: BLE001
        return None


def apply_extensions(agent: "A1", config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply configured extensions to the agent and return a summary."""

    summary: dict[str, Any] = {}
    cfg = config or {}
    esq_cfg: dict[str, Any] = cfg.get("esqlabs", {}) if isinstance(cfg.get("esqlabs"), dict) else {}
    enable_tools = _bool(os.getenv("BIOMNI_ENABLE_ESQLABS_TOOLS"), False)
    enable_data = _bool(os.getenv("BIOMNI_ENABLE_ESQLABS_DATA"), False)
    namespaces = None

    if esq_cfg:
        enable_tools = _bool(esq_cfg.get("enable_tools"), enable_tools)
        enable_data = _bool(esq_cfg.get("enable_data_descriptors"), enable_data)
        candidate = esq_cfg.get("namespaces")
        namespaces = _normalize_namespaces(candidate) or namespaces

    if enable_tools:
        try:
            from biomni_esqlabs_tools import registry as esq_registry
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("ESQlabs tools requested but biomni_esqlabs_tools is unavailable: %s", exc)
        else:
            registered = esq_registry.register_with_agent(agent, namespaces=namespaces)
            summary["esqlabs_tools"] = {"registered": registered}
            try:
                from biomni_esqlabs_tools.data_lake.descriptors import (
                    ESQLABS_DATA_LAKE,
                    ESQLABS_LIBRARY_CONTENT,
                )
            except Exception:  # pragma: no cover
                LOGGER.debug("ESQlabs descriptors not importable", exc_info=True)
            else:
                _merge_env_descriptors(agent, enable_data, ESQLABS_DATA_LAKE, ESQLABS_LIBRARY_CONTENT)

    return summary


__all__ = ["apply_extensions", "load_extension_config"]
