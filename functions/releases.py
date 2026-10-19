import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_STORAGE_PATH = os.getenv("RELEASE_STORAGE_PATH", "last_announced_release.txt")


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


def get_last_announced_tag() -> Optional[str]:
    try:
        with open(_STORAGE_PATH) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def set_last_announced_tag(tag: str) -> None:
    dir_path = os.path.dirname(os.path.abspath(_STORAGE_PATH))
    os.makedirs(dir_path, exist_ok=True)
    with open(_STORAGE_PATH, "w") as f:
        f.write(tag)


def format_release_announcement(release: Dict[str, Any]) -> str:
    tag = release.get("tag_name", "")
    name = release.get("name") or tag
    body = (release.get("body") or "").strip()
    url = release.get("html_url", "")

    header = f"**🚀 {name}**\n"
    footer = f"\n-# {url}"

    max_body = 2000 - len(header) - len(footer)
    if len(body) > max_body:
        body = body[:max_body - 1] + "…"

    return header + (body + "\n" if body else "") + footer
