import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def get_latest_github_release(repo: str, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest published release from the GitHub API.
    Returns None if no releases exist or the latest is a draft/pre-release.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()

    release = response.json()
    if release.get("draft") or release.get("prerelease"):
        return None
    return release


def format_release_announcement(release: Dict[str, Any]) -> str:
    tag = release.get("tag_name", "")
    name = release.get("name") or tag
    body = (release.get("body") or "").strip()

    header = f"**🚀 {name}**\n"
    # Tag embedded as subtext so channel history can be used as idempotency store.
    footer = f"\n-# {tag}"

    max_body = 2000 - len(header) - len(footer)
    if len(body) > max_body:
        body = body[:max_body - 1] + "…"

    return header + (body + "\n" if body else "") + footer
