"""
Where the HTML comes from.

Two ways to feed the dragon:
  * LiveSource   — crawls a real website over the internet.
  * FolderSource — reads a folder of .html files on your computer
                   (great for checking a site BEFORE you deploy it).

Both hand back a SiteSnapshot, so the checks never care which one ran.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

USER_AGENT = "DragonfireSEO/1.0 (+https://sarahjhill.com)"
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "screenshots",
             "Claude outputs", "dist-old", ".vscode", "staticfiles"}
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4",
            ".mp3", ".css", ".js", ".ico", ".xml", ".txt", ".json", ".woff", ".woff2", ".avif")


@dataclass
class Page:
    url: str                    # public URL of the page
    html: str
    status: int = 200
    elapsed_ms: int | None = None
    path: str | None = None     # file path (folder mode only)


@dataclass
class SiteSnapshot:
    mode: str                   # "live" or "folder"
    base_url: str               # e.g. https://sarahjhill.com
    pages: list[Page] = field(default_factory=list)
    robots_txt: str | None = None
    sitemap_xml: str | None = None
    llms_txt: str | None = None
    has_custom_404: bool | None = None
    soft_404: bool | None = None         # a missing page answered "200 OK"
    https_redirect: bool | None = None   # http:// bounces to https://
    broken_links: dict = field(default_factory=dict)   # target -> [pages linking to it]
    asset_sizes: dict = field(default_factory=dict)    # absolute asset url -> bytes
    notes: list[str] = field(default_factory=list)


def normalise(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


# --------------------------------------------------------------------------- #
# Live websites
# --------------------------------------------------------------------------- #
class UnsafeTarget(ValueError):
    """Raised when someone tries to point the tool at a private/internal address."""


def assert_public_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if os.environ.get("DRAGONFIRE_ALLOW_PRIVATE_HOSTS") == "1":
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeTarget(f"Can't find {host}. Typo?") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise UnsafeTarget(f"{host} points at a private address. Not torching that.")


class LiveSource:
    def __init__(self, start_url: str, max_pages: int = 40, timeout: int = 15):
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url
        self.start_url = start_url
        self.max_pages = max_pages
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _get(self, url, **kw):
        try:
            return self.session.get(url, timeout=self.timeout, allow_redirects=True, **kw)
        except requests.RequestException:
            return None

    def snapshot(self) -> SiteSnapshot:
        assert_public_host(self.start_url)
        first = self._get(self.start_url)
        if first is None:
            raise ConnectionError(f"Couldn't reach {self.start_url}.")
        final = urlparse(first.url)
        base = f"{final.scheme}://{final.netloc}"
        host = final.netloc.lower()
        snap = SiteSnapshot(mode="live", base_url=base)

        # robots / sitemap / llms.txt
        for attr, name in (("robots_txt", "robots.txt"), ("sitemap_xml", "sitemap.xml"),
                           ("llms_txt", "llms.txt")):
            r = self._get(f"{base}/{name}")
            if r is not None and r.status_code == 200 and "<html" not in r.text[:500].lower():
                setattr(snap, attr, r.text)

        # Does a page that doesn't exist answer 404?
        r = self._get(f"{base}/dragonfire-{uuid.uuid4().hex[:8]}")
        if r is not None:
            snap.soft_404 = r.status_code == 200
            snap.has_custom_404 = r.status_code == 404 and len(r.text) > 300

        # http -> https?
        try:
            r = self.session.get(f"http://{final.netloc}/", timeout=self.timeout, allow_redirects=True)
            snap.https_redirect = r.url.startswith("https://")
        except requests.RequestException:
            snap.https_redirect = None

        # Seed the crawl with the homepage and anything in the sitemap
        queue = deque([normalise(first.url)])
        if snap.sitemap_xml:
            soup = BeautifulSoup(snap.sitemap_xml, "html.parser")
            for loc in soup.find_all("loc"):
                u = loc.get_text(strip=True)
                if urlparse(u).netloc.lower().replace("www.", "") == host.replace("www.", ""):
                    queue.append(normalise(u))

        seen, linked_from = set(), {}
        while queue and len(snap.pages) < self.max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            t0 = time.perf_counter()
            r = self._get(url)
            elapsed = int((time.perf_counter() - t0) * 1000)
            if r is None or r.status_code >= 400:
                status = r.status_code if r is not None else 0
                snap.broken_links.setdefault(url, linked_from.get(url, []))
                if status == 0:
                    snap.notes.append(f"Timed out: {url}")
                continue
            if "text/html" not in r.headers.get("Content-Type", ""):
                continue
            snap.pages.append(Page(url=normalise(r.url), html=r.text,
                                   status=r.status_code, elapsed_ms=elapsed))
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                target = normalise(urljoin(r.url, a["href"]))
                p = urlparse(target)
                if p.scheme not in ("http", "https") or p.netloc.lower() != host:
                    continue
                if p.path.lower().endswith(SKIP_EXT):
                    continue
                linked_from.setdefault(target, []).append(normalise(r.url))
                if target not in seen:
                    queue.append(target)

        # Image weights (HEAD requests, capped so we stay polite)
        imgs = []
        for page in snap.pages:
            soup = BeautifulSoup(page.html, "html.parser")
            for img in soup.find_all("img", src=True):
                imgs.append(urljoin(page.url, img["src"]))
        for src in list(dict.fromkeys(imgs))[:60]:
            try:
                h = self.session.head(src, timeout=self.timeout, allow_redirects=True)
                if h.headers.get("Content-Length"):
                    snap.asset_sizes[src] = int(h.headers["Content-Length"])
            except requests.RequestException:
                pass
        if len(snap.pages) >= self.max_pages:
            snap.notes.append(f"Stopped at {self.max_pages} pages. Raise --max-pages to go deeper.")
        return snap


# --------------------------------------------------------------------------- #
# Local folders
# --------------------------------------------------------------------------- #
class FolderSource:
    def __init__(self, root: str, base_url: str | None = None):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"No folder at {self.root}")
        if not base_url:
            cname = self.root / "CNAME"
            base_url = f"https://{cname.read_text().strip()}" if cname.exists() else "https://example.com"
        self.base_url = base_url.rstrip("/")

    def _read(self, name):
        p = self.root / name
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    def _url_for(self, file: Path) -> str:
        rel = file.relative_to(self.root).as_posix()
        if rel == "index.html":
            rel = ""
        elif rel.endswith("/index.html"):
            rel = rel[: -len("index.html")]
        return normalise(f"{self.base_url}/{rel}")

    def _file_for(self, url: str) -> Path | None:
        """Map a public URL back to a file in the folder, like a static host would."""
        path = urlparse(url).path.lstrip("/")
        if not path:
            index = self.root / "index.html"
            return index if index.is_file() else None
        for c in (path, path.rstrip("/") + "/index.html", path + ".html"):
            f = self.root / c
            if f.is_file():
                return f
        return None

    def snapshot(self) -> SiteSnapshot:
        snap = SiteSnapshot(mode="folder", base_url=self.base_url)
        snap.robots_txt = self._read("robots.txt")
        snap.sitemap_xml = self._read("sitemap.xml")
        snap.llms_txt = self._read("llms.txt")
        snap.has_custom_404 = (self.root / "404.html").exists()
        snap.soft_404 = None
        snap.https_redirect = None
        host = urlparse(self.base_url).netloc

        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".html"):
                    files.append(Path(dirpath) / fn)
        for f in sorted(files):
            if f.name == "404.html":
                continue
            snap.pages.append(Page(url=self._url_for(f), html=f.read_text(encoding="utf-8", errors="replace"),
                                   path=str(f.relative_to(self.root))))

        # Broken internal links + image weights, resolved against the folder
        for page in snap.pages:
            soup = BeautifulSoup(page.html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(("mailto:", "tel:", "#", "javascript:", "sms:")):
                    continue
                target = urljoin(page.url, href)
                p = urlparse(target)
                if p.netloc != host:
                    continue
                if self._file_for(target) is None:
                    snap.broken_links.setdefault(normalise(target), []).append(page.url)
            for img in soup.find_all("img", src=True):
                src = urljoin(page.url, img["src"])
                if urlparse(src).netloc != host:
                    continue
                f = self.root / urlparse(src).path.lstrip("/")
                if f.is_file():
                    snap.asset_sizes[src] = f.stat().st_size
        return snap


def make_source(target: str, max_pages: int = 40, base_url: str | None = None):
    """A folder path → FolderSource. Anything else → LiveSource."""
    expanded = os.path.expanduser(target)
    if os.path.isdir(expanded):
        return FolderSource(expanded, base_url=base_url)
    return LiveSource(target, max_pages=max_pages)
