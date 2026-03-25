from __future__ import annotations

import time

import httpx
import jwt

from .config import GitHubSettings
from .github_api import GitHubClient
from .runtime import AppSettings


class GitHubAppAuthError(RuntimeError):
    pass


class GitHubAppClient:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.github_api_url,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": settings.github_api_version,
                "User-Agent": "ai-pr-review-bot",
            },
        )

    def close(self) -> None:
        self._client.close()

    def generate_app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 9 * 60,
            "iss": self._settings.github_app_id,
        }
        return str(jwt.encode(payload, self._settings.github_private_key, algorithm="RS256"))

    def create_installation_token(self, installation_id: int) -> str:
        jwt_token = self.generate_app_jwt()
        response = self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token")
        if not token:
            raise GitHubAppAuthError("GitHub did not return an installation access token.")
        return str(token)

    def create_repo_client(self, installation_id: int, repo_full_name: str, github_settings: GitHubSettings) -> GitHubClient:
        token = self.create_installation_token(installation_id)
        return GitHubClient.from_token(token=token, repo_full_name=repo_full_name, settings=github_settings)
