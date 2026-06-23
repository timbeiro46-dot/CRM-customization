from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from crm_agent.errors import ConfigurationError


def load_dotenv(path: Path = Path(".env")) -> None:
    """Tiny .env loader to avoid adding another runtime dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    hubspot_private_app_token: str
    hubspot_base_url: str = "https://api.hubapi.com"
    hubspot_api_version: str = "2026-03"
    outdir: Path = Path(".")
    timeout_seconds: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_env(cls, *, require_token: bool = True) -> Settings:
        load_dotenv()
        token = os.getenv("HUBSPOT_PRIVATE_APP_TOKEN", "").strip()
        if require_token and not token:
            raise ConfigurationError(
                "Missing HUBSPOT_PRIVATE_APP_TOKEN. Copy .env.example to .env "
                "and set a private app token. Run `crm-agent setup-legacy-app` "
                "for the required HubSpot setup steps."
            )
        return cls(
            hubspot_private_app_token=token,
            hubspot_base_url=os.getenv("HUBSPOT_BASE_URL", "https://api.hubapi.com").rstrip("/"),
            hubspot_api_version=os.getenv("HUBSPOT_API_VERSION", "2026-03"),
            outdir=Path(os.getenv("CRM_AGENT_OUTDIR", ".")),
            timeout_seconds=float(os.getenv("CRM_AGENT_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("CRM_AGENT_MAX_RETRIES", "3")),
        )


def read_yaml_file(path: Path) -> dict:
    if not path.exists():
        raise ConfigurationError(f"File not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"Expected mapping YAML in {path}")
    return data
