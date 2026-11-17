import random
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


class FetchError(Exception):
    pass


class PoliteFetcher:
    def __init__(
        self,
        delay=1.0,
        timeout=20,
        max_retries=3,
        respect_robots=True,
        user_agent="immo-agent/1.0 (+contact: admin@example.local)",
    ):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9",
            }
        )
        self._robots = {}
        self._last_request = {}

    @staticmethod
    def _host(url):
        return urlparse(url).netloc

    def _robots_parser(self, url):
        host = self._host(url)
        if host not in self._robots:
            scheme = urlparse(url).scheme or "https"
            parser = RobotFileParser()
            parser.set_url(f"{scheme}://{host}/robots.txt")
            try:
                parser.read()
            except Exception:
                pass
            self._robots[host] = parser
        return self._robots[host]

    def can_fetch(self, url):
        if not self.respect_robots:
            return True
        return self._robots_parser(url).can_fetch(
            self.session.headers["User-Agent"], url
        )

    def _wait(self, url):
        host = self._host(url)
        last = self._last_request.get(host, 0.0)
        wait = self.delay + random.uniform(0, 0.5) - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get_json(self, url):
        if not self.can_fetch(url):
            raise FetchError(f"robots.txt interdit l'acces a : {url}")
        last_error = None
        for attempt in range(self.max_retries):
            try:
                self._wait(url)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} pour {url}")
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise FetchError(f"echec du telechargement de {url} : {last_error}")

    def open_stream(self, url, timeout=None):
        if not self.can_fetch(url):
            raise FetchError(f"robots.txt interdit l'acces a : {url}")
        self._wait(url)
        return self.session.get(url, stream=True, timeout=timeout or self.timeout)

    def get(self, url):
        if not self.can_fetch(url):
            raise FetchError(f"robots.txt interdit l'acces a : {url}")
        last_error = None
        for attempt in range(self.max_retries):
            try:
                self._wait(url)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise FetchError(f"HTTP {response.status_code} pour {url}")
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} pour {url}")
                response.encoding = response.apparent_encoding or response.encoding
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
        raise FetchError(f"echec du telechargement de {url} : {last_error}")
