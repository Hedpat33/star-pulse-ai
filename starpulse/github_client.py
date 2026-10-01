"""GitHub Search API client: per-tag queries, throttling and retries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/repositories"
USER_AGENT = "star-pulse-ai"

# Minimum seconds between search requests (search limit is per-minute).
INTERVAL_WITH_TOKEN = 2.1
INTERVAL_ANONYMOUS = 6.2
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # 2s -> 4s -> 8s

PER_PAGE = 100
# GitHub Search only serves the first 1000 matching items (10 pages of 100).
SEARCH_RESULT_CAP = 1000

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 15


class Repo:
    """One GitHub repository row shared by fetch, snapshot and render."""

    __slots__ = ("full_name", "stars", "description", "html_url", "topics")

    def __init__(
        self,
        full_name: str,
        stars: int,
        description: str = "",
        html_url: str = "",
        topics: Optional[Sequence[str]] = None,
    ) -> None:
        self.full_name = full_name
        self.stars = stars
        self.description = description
        self.html_url = html_url
        self.topics: List[str] = list(topics or [])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Repo):
            return NotImplemented
        return (
            self.full_name == other.full_name
            and self.stars == other.stars
            and self.description == other.description
            and self.html_url == other.html_url
            and self.topics == other.topics
        )

    def __repr__(self) -> str:
        return f"Repo(full_name={self.full_name!r}, stars={self.stars})"


@dataclass
class FetchResult:
    """Outcome of one fetch round: merged candidates plus failed tags."""

    pool: List[Repo] = field(default_factory=list)
    failed_tags: List[str] = field(default_factory=list)


class GitHubClient:
    """Fetches repositories per topic tag with rate-limit friendly pacing."""

    def __init__(
        self,
        token: Optional[str] = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token = token
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic
        self._interval = INTERVAL_WITH_TOKEN if token else INTERVAL_ANONYMOUS
        self._last_request_at: Optional[float] = None

    # -- public API ---------------------------------------------------------

    def fetch_candidates(self, tags: Sequence[str], min_stars: int) -> FetchResult:
        """Query every page of each tag and merge results, recording failed tags."""
        result = FetchResult()
        merged: Dict[str, Repo] = {}
        for tag in tags:
            try:
                items = self._search_tag(tag, min_stars)
            except requests.RequestException as exc:
                logger.error("tag %r failed after retries: %s", tag, exc)
                result.failed_tags.append(tag)
                continue
            logger.info("tag %r: %d item(s)", tag, len(items))
            for repo in items:
                existing = merged.get(repo.full_name)
                if existing is None or repo.stars > existing.stars:
                    merged[repo.full_name] = repo
        result.pool = list(merged.values())
        return result

    # -- internals ----------------------------------------------------------

    def _search_tag(self, tag: str, min_stars: int) -> List[Repo]:
        repos: List[Repo] = []
        page = 1
        while True:
            data = self._request_json(self._params(tag, min_stars, page))
            items = data.get("items", [])
            for item in items:
                repos.append(
                    Repo(
                        full_name=item.get("full_name", ""),
                        stars=int(item.get("stargazers_count", 0)),
                        description=item.get("description") or "",
                        html_url=item.get("html_url", ""),
                        topics=item.get("topics") or [],
                    )
                )
            total = int(data.get("total_count", 0))
            # Stop when the page is short (last page), the total is drained,
            # or the 1000-result search cap makes further pages useless.
            if len(items) < PER_PAGE:
                break
            page += 1
            if (page - 1) * PER_PAGE >= min(total, SEARCH_RESULT_CAP):
                if total > SEARCH_RESULT_CAP:
                    logger.warning(
                        "tag %r: %d match(es) exceed the %d search cap; "
                        "results truncated",
                        tag, total, SEARCH_RESULT_CAP,
                    )
                break
        return [r for r in repos if r.full_name]

    @staticmethod
    def _params(tag: str, min_stars: int, page: int) -> dict:
        return {
            "q": f"topic:{tag} stars:>{min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": PER_PAGE,
            "page": page,
        }

    def _request_json(self, params: dict) -> dict:
        last_exc: Optional[requests.RequestException] = None
        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                self._last_request_at = self._monotonic()
                response = self._session.get(
                    SEARCH_URL,
                    params=params,
                    headers=self._headers(),
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.RequestException as exc:
                last_exc = exc
                self._backoff(attempt, f"network error: {exc}")
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code in (403, 429):
                delay = self._rate_limit_delay(response, attempt)
                logger.warning(
                    "rate limited (HTTP %d), waiting %.1fs", response.status_code, delay
                )
                self._sleep(delay)
                continue
            if response.status_code >= 500:
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            # 4xx other than rate limits: retrying will not help.
            raise requests.RequestException(
                f"unexpected HTTP {response.status_code} for params={params}"
            )
        raise last_exc or requests.RequestException("request failed")

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        wait = self._interval - elapsed
        if wait > 0:
            self._sleep(wait)

    def _rate_limit_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return BACKOFF_BASE * (2 ** attempt)

    def _backoff(self, attempt: int, reason: str) -> None:
        if attempt >= MAX_RETRIES:
            return
        delay = BACKOFF_BASE * (2 ** attempt)
        logger.warning("%s; retrying in %.1fs", reason, delay)
        self._sleep(delay)


def dedupe(pool: Sequence[Repo]) -> List[Repo]:
    """Deduplicate by full_name (keep the highest star count), stars desc then name."""
    merged: Dict[str, Repo] = {}
    for repo in pool:
        existing = merged.get(repo.full_name)
        if existing is None or repo.stars > existing.stars:
            merged[repo.full_name] = repo
    return sorted(merged.values(), key=lambda r: (-r.stars, r.full_name))
