import os

from services.keyvault_service import get_secret


def setting(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing application setting: {name}")
    return value


def required_setting(name: str, default: str | None = None) -> str:
    # Secrets are resolved from Key Vault references in Azure and supplied
    # as local-only environment values during local development.
    if name in {"GITHUB_PAT", "SQL_USERNAME", "SQL_PASSWORD"}:
        if default is not None:
            raise ValueError("Do not provide defaults for secret settings.")
        return get_secret(name)
    return setting(name, default)
