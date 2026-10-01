"""Tests for starpulse.github_client using a fake session (no real network)."""

import unittest
from typing import List, Optional

import requests

from starpulse.github_client import (
    INTERVAL_ANONYMOUS,
    INTERVAL_WITH_TOKEN,
    PER_PAGE,
    GitHubClient,
    Repo,
    dedupe,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict] = None,
                 headers: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Scripted session: pops the next response/exception per request."""

    def __init__(self, script: List[object]):
        self.script = list(script)
        self.calls: List[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers,
                           "timeout": timeout})
        if not self.script:
            raise AssertionError("FakeSession script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def repo(name: str, stars: int) -> Repo:
    return Repo(full_name=name, stars=stars, html_url=f"https://github.com/{name}")


def search_ok(*names_and_stars) -> FakeResponse:
    items = [
        {"full_name": n, "stargazers_count": s, "description": "d",
         "html_url": f"https://github.com/{n}", "topics": ["ai"]}
        for n, s in names_and_stars
    ]
    return FakeResponse(200, {"items": items})


def search_page(total: int, page: int, count: int) -> FakeResponse:
    """A page of `count` items from a result set of `total` matches."""
    items = [
        {"full_name": f"a/r{page}-{i}", "stargazers_count": 1000 - i,
         "description": "d", "html_url": "https://github.com/x", "topics": ["ai"]}
        for i in range(count)
    ]
    return FakeResponse(200, {"total_count": total, "items": items})


class FetchCandidatesTest(unittest.TestCase):
    def make_client(self, script, token=None):
        sleeps: List[float] = []
        clock = {"now": 1000.0}

        def monotonic() -> float:
            return clock["now"]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock["now"] += seconds

        session = FakeSession(script)
        client = GitHubClient(token=token, session=session,
                              sleep=sleep, monotonic=monotonic)
        return client, session, sleeps

    def test_query_contains_topic_and_star_filter(self):
        client, session, _ = self.make_client(
            [search_ok(("a/one", 9000))], token="t"
        )
        client.fetch_candidates(["ai"], min_stars=5000)
        params = session.calls[0]["params"]
        self.assertEqual(params["q"], "topic:ai stars:>5000")
        self.assertEqual(params["sort"], "stars")
        self.assertEqual(params["order"], "desc")
        self.assertEqual(params["per_page"], 100)

    def test_auth_header_sent_with_token_absent_without(self):
        with_token, session_t, _ = self.make_client([search_ok(("a/one", 1))], token="abc")
        with_token.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(session_t.calls[0]["headers"]["Authorization"], "Bearer abc")

        anon, session_a, _ = self.make_client([search_ok(("a/one", 1))])
        anon.fetch_candidates(["ai"], min_stars=5000)
        self.assertNotIn("Authorization", session_a.calls[0]["headers"])

    def test_multi_tag_deduplication_keeps_highest_stars(self):
        client, _, _ = self.make_client(
            [search_ok(("a/one", 9000), ("a/two", 8000)),
             search_ok(("a/one", 9500), ("a/three", 7000))],
            token="t",
        )
        result = client.fetch_candidates(["ai", "llm"], min_stars=5000)
        self.assertEqual(result.failed_tags, [])
        by_name = {r.full_name: r.stars for r in result.pool}
        self.assertEqual(by_name, {"a/one": 9500, "a/two": 8000, "a/three": 7000})

    def test_single_tag_failure_does_not_break_round(self):
        # Tag "ai" fails all 4 attempts (1 + 3 retries), then tag "llm" succeeds.
        client, _, _ = self.make_client(
            [requests.ConnectionError("boom"), requests.ConnectionError("boom"),
             requests.ConnectionError("boom"), requests.ConnectionError("boom"),
             search_ok(("a/one", 9000))],
            token="t",
        )
        result = client.fetch_candidates(["ai", "llm"], min_stars=5000)
        self.assertEqual(result.failed_tags, ["ai"])
        self.assertEqual([r.full_name for r in result.pool], ["a/one"])

    def test_rate_limit_honors_retry_after(self):
        sleeps: List[float] = []
        clock = {"now": 0.0}
        session = FakeSession([
            FakeResponse(429, headers={"Retry-After": "7"}),
            search_ok(("a/one", 9000)),
        ])
        client = GitHubClient(
            token="t", session=session,
            sleep=lambda s: (sleeps.append(s), clock.__setitem__("now", clock["now"] + s)),
            monotonic=lambda: clock["now"],
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertIn(7.0, sleeps)
        self.assertEqual(result.failed_tags, [])

    def test_rate_limit_without_retry_after_uses_backoff(self):
        sleeps: List[float] = []
        clock = {"now": 0.0}
        session = FakeSession([
            FakeResponse(429),
            FakeResponse(429),
            search_ok(("a/one", 9000)),
        ])
        client = GitHubClient(
            token="t", session=session,
            sleep=lambda s: (sleeps.append(s), clock.__setitem__("now", clock["now"] + s)),
            monotonic=lambda: clock["now"],
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        # Backoff delays 2s then 4s; a 0.1s throttle gap may sit between them.
        self.assertEqual(sleeps[0], 2.0)
        self.assertIn(4.0, sleeps)
        self.assertEqual(result.failed_tags, [])

    def test_persistent_failure_marks_tag_failed(self):
        client, _, _ = self.make_client(
            [FakeResponse(404), FakeResponse(404), FakeResponse(404), FakeResponse(404)],
            token="t",
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(result.failed_tags, ["ai"])
        self.assertEqual(result.pool, [])

    def test_throttle_interval_differs_with_token(self):
        # Two tags -> two requests; the pacing gap shows up as one sleep entry.
        client_t, _, sleeps_token = self.make_client(
            [search_ok(("a/one", 1)), search_ok(("b/x", 1))], token="t"
        )
        client_t.fetch_candidates(["ai", "llm"], min_stars=5000)

        client_a, _, sleeps_anon = self.make_client(
            [search_ok(("a/one", 1)), search_ok(("b/x", 1))]
        )
        client_a.fetch_candidates(["ai", "llm"], min_stars=5000)

        self.assertEqual(sleeps_token, [INTERVAL_WITH_TOKEN])
        self.assertEqual(sleeps_anon, [INTERVAL_ANONYMOUS])

    def test_network_error_retries_then_succeeds(self):
        client, session, sleeps = self.make_client(
            [requests.Timeout("t1"), search_ok(("a/one", 9000))], token="t"
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(result.failed_tags, [])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps[0], 2.0)

    def test_pagination_fetches_all_pages(self):
        # 150 matches -> two pages: a full first page, then a short one.
        client, session, _ = self.make_client(
            [search_page(150, 1, PER_PAGE), search_page(150, 2, 50)], token="t"
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(result.failed_tags, [])
        self.assertEqual(len(result.pool), 150)
        self.assertEqual(
            [c["params"]["page"] for c in session.calls], [1, 2]
        )

    def test_single_page_when_results_fit(self):
        client, session, _ = self.make_client(
            [search_page(42, 1, 42)], token="t"
        )
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(len(result.pool), 42)
        self.assertEqual(len(session.calls), 1)

    def test_pagination_stops_at_search_cap(self):
        # total_count above the 1000 cap: fetch 10 pages then stop.
        script = [search_page(5000, p, PER_PAGE) for p in range(1, 11)]
        script.append(search_page(5000, 11, PER_PAGE))  # must never be used
        client, session, _ = self.make_client(script, token="t")
        result = client.fetch_candidates(["ai"], min_stars=5000)
        self.assertEqual(len(result.pool), 10 * PER_PAGE)
        self.assertEqual(len(session.calls), 10)
        self.assertEqual(result.failed_tags, [])


class DedupeTest(unittest.TestCase):
    def test_sorts_by_stars_then_name_and_keeps_all(self):
        pool = [
            repo("b/low", 6000),
            repo("a/high", 9000),
            repo("c/mid", 9000),
            repo("d/out", 1000),
        ]
        ranked = dedupe(pool)
        self.assertEqual(
            [r.full_name for r in ranked],
            ["a/high", "c/mid", "b/low", "d/out"],
        )

    def test_dedupes_by_full_name_keeping_max(self):
        pool = [repo("a/one", 9000), repo("a/one", 9500)]
        ranked = dedupe(pool)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].stars, 9500)


if __name__ == "__main__":
    unittest.main()
