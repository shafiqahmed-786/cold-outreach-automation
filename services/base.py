"""
Base async HTTP client shared by all service wrappers.

Uses a single aiohttp.ClientSession per service instance to enable
connection pooling. Sessions are created lazily and closed via context
manager or explicit close().
"""

from __future__ import annotations

import aiohttp
from core.config import get_config
from core.logger import get_logger

logger = get_logger(__name__)


class BaseAPIClient:
    """Async HTTP client with session lifecycle management."""

    base_url: str = ""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._cfg = get_config()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._cfg.REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("%s session closed.", self.__class__.__name__)

    async def __aenter__(self) -> "BaseAPIClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Convenience wrappers that raise on non-2xx
    # ------------------------------------------------------------------

    async def _get(self, path: str, headers: dict, params: dict | None = None) -> dict:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        logger.debug("GET %s params=%s", url, params)
        async with session.get(url, headers=headers, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, headers: dict, payload: dict) -> dict:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        logger.debug("POST %s", url)
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()