"""Web search tool via DuckDuckGo Lite (stdlib only)."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_TIMEOUT_SEC = 15
_MAX_RESULTS = 5
_USER_AGENT = "Mozilla/5.0 (compatible; JarvisPi/1.0)"


class _LiteResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str, str]] = []
        self._in_result_link = False
        self._current_title = ""
        self._current_href = ""
        self._capture_snippet = False
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        if tag == "a" and attr_map.get("class") == "result-link":
            self._in_result_link = True
            self._current_href = urljoin(_DDG_LITE_URL, attr_map.get("href", ""))
            self._current_title = ""
            return
        if tag == "td" and self._capture_snippet:
            return
        if tag == "span" and attr_map.get("class") == "result-snippet":
            self._capture_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            self._in_result_link = False
            title = " ".join(self._current_title.split())
            if title and self._current_href:
                snippet = " ".join("".join(self._snippet_parts).split())
                self.results.append((title, snippet, self._current_href))
            self._current_title = ""
            self._current_href = ""
            self._snippet_parts = []
            self._capture_snippet = False
            return
        if tag == "span" and self._capture_snippet:
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._current_title += data
        elif self._capture_snippet:
            self._snippet_parts.append(data)


def _parse_lite_html(html: str) -> list[tuple[str, str, str]]:
    parser = _LiteResultParser()
    parser.feed(html)
    if parser.results:
        return parser.results[:_MAX_RESULTS]

    fallback: list[tuple[str, str, str]] = []
    for chunk in html.split('class="result-link"'):
        if len(fallback) >= _MAX_RESULTS:
            break
        if 'href="' not in chunk:
            continue
        href_start = chunk.find('href="') + 6
        href_end = chunk.find('"', href_start)
        if href_end == -1:
            continue
        href = urljoin(_DDG_LITE_URL, chunk[href_start:href_end])
        text_start = chunk.find(">", href_end) + 1
        text_end = chunk.find("</a>", text_start)
        if text_end == -1:
            continue
        title = " ".join(chunk[text_start:text_end].split())
        if title:
            fallback.append((title, "", href))
    return fallback[:_MAX_RESULTS]


def search(query: str) -> str:
    query = query.strip()
    if not query:
        return "Ошибка: пустой поисковый запрос."

    body = f"q={quote_plus(query)}".encode("utf-8")
    request = Request(
        _DDG_LITE_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SEC) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        return f"Ошибка поиска: HTTP {exc.code}."
    except (TimeoutError, URLError, OSError):
        return "Ошибка поиска: не удалось связаться с DuckDuckGo."

    results = _parse_lite_html(html)
    if not results:
        return "По запросу ничего не найдено."

    lines: list[str] = []
    for index, (title, snippet, href) in enumerate(results, start=1):
        line = f"{index}. {title}"
        if snippet:
            line += f" — {snippet}"
        line += f" ({href})"
        lines.append(line)
    return "\n".join(lines)
