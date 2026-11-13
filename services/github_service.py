import requests

from shared.config import required_setting


def download_csv(csv_path: str) -> bytes:
    """
    Download a CSV from a private GitHub repository.

    GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH and GITHUB_PAT are
    supplied through Function App settings. In Azure, GITHUB_PAT is
    configured as a Key Vault reference.
    """
    owner = required_setting("GITHUB_OWNER")
    repo = required_setting("GITHUB_REPO")
    branch = required_setting("GITHUB_BRANCH", "main")
    token = required_setting("GITHUB_PAT")

    from urllib.parse import quote

    encoded_path = quote(csv_path.lstrip("/"), safe="/")
    encoded_branch = quote(branch, safe="")
    url = (
        f"https://raw.githubusercontent.com/"
        f"{owner}/{repo}/{encoded_branch}/{encoded_path}"
    )

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw",
            "User-Agent": "olist-azure-function",
        },
        timeout=(10, 120),
    )
    response.raise_for_status()

    if not response.content:
        raise ValueError(f"GitHub returned an empty CSV: {csv_path}")

    return response.content
