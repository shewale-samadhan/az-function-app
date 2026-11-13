"""
Key Vault access is provided through App Service Key Vault references.

In Azure, configure GITHUB_PAT, SQL_USERNAME and SQL_PASSWORD app settings
with values such as:
@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/<name>/)

Azure resolves those references using the Function App's managed identity.
Application code reads the resolved values from environment variables.
This module deliberately does not fetch secrets directly with an SDK.
"""

import os


def get_secret(setting_name: str) -> str:
    value = os.getenv(setting_name)
    if not value:
        raise RuntimeError(
            f"Missing setting '{setting_name}'. Check the Function App "
            "application setting and its Key Vault reference."
        )
    return value
