"""ai4trade.ai REST client.

Thin requests wrapper for the public ai4trade API. State (bearer token,
agent id, followed leaders, last-seen signal id) lives in the
copytrade_state Postgres table — this client only hits the wire.

Endpoints used (verified against https://ai4trade.ai/openapi.json):
  POST /api/claw/agents/selfRegister   { name, password } -> { token, agent_id }
  GET  /api/agents/top?limit=N&sort=return
  POST /api/signals/follow             { leader_id }      (Bearer)
  POST /api/signals/unfollow           { leader_id }      (Bearer)
  GET  /api/signals/feed?limit=&offset=&sort=new          (Bearer optional)
  GET  /api/signals/following                             (Bearer)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ai4trade.ai"
# ai4trade.ai responses commonly take 30–45s; give a wide margin.
DEFAULT_TIMEOUT = 90


class AI4TradeError(RuntimeError):
    """Raised on non-2xx responses from ai4trade."""


class AI4TradeClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {"content-type": "application/json", "accept": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._session.request(
            method, url, headers=self._headers(auth=auth), timeout=self.timeout, **kwargs
        )
        if resp.status_code >= 400:
            raise AI4TradeError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return resp.json()
        return resp.text

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def self_register(self, name: str, password: str) -> dict:
        """Create a new agent and return {token, agent_id, name, initial_balance, ...}.

        Stores the token on this client so subsequent calls authenticate.
        """
        data = self._request(
            "POST",
            "/api/claw/agents/selfRegister",
            auth=False,
            json={"name": name, "password": password},
        )
        if not isinstance(data, dict) or "token" not in data:
            raise AI4TradeError(f"selfRegister returned unexpected payload: {data!r}")
        self.token = data["token"]
        return data

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_top_agents(self, limit: int = 10, sort: str = "return") -> list[dict]:
        """Return the leaderboard. Best-effort — the endpoint is heavy and may 504."""
        data = self._request(
            "GET",
            "/api/agents/top",
            params={"limit": limit, "sort": sort},
            auth=False,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("agents", "data", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    # ------------------------------------------------------------------
    # Follow graph
    # ------------------------------------------------------------------

    def follow(self, leader_id: int) -> dict:
        return self._request("POST", "/api/signals/follow", json={"leader_id": leader_id}) or {}

    def unfollow(self, leader_id: int) -> dict:
        return self._request("POST", "/api/signals/unfollow", json={"leader_id": leader_id}) or {}

    def list_following(self) -> list[dict]:
        data = self._request("GET", "/api/signals/following")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("following", "data", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    # ------------------------------------------------------------------
    # Feed
    # ------------------------------------------------------------------

    def get_feed(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str = "following",
        market: str | None = None,
        message_type: str | None = None,
    ) -> list[dict]:
        """Return a list of recent signals.

        sort="following" filters to followed leaders (requires auth). The skill
        documents this as the consumer copy-trade path. sort="new" returns the
        global firehose (no auth required) — useful for bootstrap when we
        haven't picked leaders yet.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset, "sort": sort}
        if market:
            params["market"] = market
        if message_type:
            params["message_type"] = message_type
        data = self._request("GET", "/api/signals/feed", params=params, auth=True)
        if isinstance(data, dict) and "signals" in data:
            return data["signals"] or []
        if isinstance(data, list):
            return data
        return []
