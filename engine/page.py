"""
Turns raw HTML into plain facts (title, headings, schema, links...).
Checks read these facts — they never touch HTML directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .sources import Page, normalise

UK_PHONE = re.compile(r"(?:\+44\s?|\b0)(?:\d[\s-]?){9,10}\b")
NUMBER_PROOF = re.compile(r"(\b\d{2,}\b\s?(?:%|\+|years?|jobs?|clients?|projects?|reviews?|customers?))|(£\s?\d)|(\b\d+%)", re.I)
WORD = re.compile(r"[A-Za-zÀ-ÿ0-9']+")


@dataclass
class PageFacts:
    url: str
    status: int
    elapsed_ms: int | None
    html_bytes: int
    title: str | None = None
    description: str | None = None
    lang: str | None = None
    has_viewport: bool = False
    canonical: str | None = None
    noindex: bool = False
    h1s: list = field(default_factory=list)
    headings: list = field(default_factory=list)          # [(level, text)]
    og: dict = field(default_factory=dict)
    twitter_card: str | None = None
    images: list = field(default_factory=list)            # dicts: src, alt, lazy, sized
    internal_links: set = field(default_factory=set)
    external_links: set = field(default_factory=set)
    word_count: int = 0
    jsonld: list = field(default_factory=list)            # parsed objects (flattened)
    jsonld_errors: int = 0
    blocking_scripts: int = 0
    stylesheets: int = 0
    tel_links: list = field(default_factory=list)
    phones: set = field(default_factory=set)
    text: str = ""
    first_paras: list = field(default_factory=list)       # first paragraph word counts after each H2
    has_date: bool = False
    has_author: bool = False
    maps_link: bool = False
    proof_points: int = 0

    @property
    def schema_types(self) -> set:
        types = set()
        for obj in self.jsonld:
            t = obj.get("@type")
            if isinstance(t, list):
                types.update(t)
            elif t:
                types.add(t)
        return types


def _flatten_jsonld(data):
    """Yield every object in a JSON-LD blob, including @graph members and nested things."""
    if isinstance(data, list):
        for item in data:
            yield from _flatten_jsonld(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _flatten_jsonld(data["@graph"])
        if "@type" in data:
            yield data
        for key, value in data.items():
            if key != "@graph" and isinstance(value, (dict, list)):
                yield from _flatten_jsonld(value)


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return "0" + d[2:] if d.startswith("44") else d


def extract(page: Page, base_url: str) -> PageFacts:
    soup = BeautifulSoup(page.html, "html.parser")
    host = urlparse(base_url).netloc.lower()
    f = PageFacts(url=page.url, status=page.status, elapsed_ms=page.elapsed_ms,
                  html_bytes=len(page.html.encode("utf-8")))

    if soup.title and soup.title.string:
        f.title = soup.title.string.strip()
    html_tag = soup.find("html")
    f.lang = html_tag.get("lang") if html_tag else None

    for m in soup.find_all("meta"):
        name = (m.get("name") or "").lower()
        prop = (m.get("property") or "").lower()
        content = (m.get("content") or "").strip()
        if name == "description":
            f.description = content
        elif name == "viewport":
            f.has_viewport = True
        elif name == "robots" and "noindex" in content.lower():
            f.noindex = True
        elif name == "author" and content:
            f.has_author = True
        elif name == "twitter:card":
            f.twitter_card = content
        elif prop.startswith("og:"):
            f.og[prop] = content
        elif prop in ("article:modified_time", "article:published_time"):
            f.has_date = True

    link = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link and link.get("href"):
        f.canonical = normalise(urljoin(page.url, link["href"]))

    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        text = " ".join(tag.get_text(" ", strip=True).split())
        level = int(tag.name[1])
        f.headings.append((level, text))
        if level == 1:
            f.h1s.append(text)

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            f.jsonld_errors += 1
            continue
        f.jsonld.extend(_flatten_jsonld(data))
    for obj in f.jsonld:
        if obj.get("dateModified") or obj.get("datePublished"):
            f.has_date = True
        if obj.get("author"):
            f.has_author = True
    if soup.find("time", attrs={"datetime": True}):
        f.has_date = True

    # Performance-ish signals from the <head>
    head = soup.find("head")
    if head:
        for s in head.find_all("script", src=True):
            if not (s.has_attr("defer") or s.has_attr("async") or s.get("type") == "module"):
                f.blocking_scripts += 1
        f.stylesheets = len(head.find_all("link", rel=lambda v: v and "stylesheet" in v))

    # Images
    for img in soup.find_all("img"):
        f.images.append({
            "src": urljoin(page.url, img.get("src", "")),
            "alt": img.get("alt"),
            "lazy": img.get("loading") == "lazy",
            "sized": bool(img.get("width") and img.get("height")),
        })

    # Links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("tel:"):
            f.tel_links.append(href[4:])
            f.phones.add(_digits(href[4:]))
            continue
        if href.startswith(("mailto:", "#", "javascript:", "sms:")):
            continue
        absolute = urljoin(page.url, href)
        p = urlparse(absolute)
        if any(m in absolute for m in ("google.com/maps", "maps.google", "g.page", "maps.app.goo.gl", "goo.gl/maps")):
            f.maps_link = True
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower() == host:
            f.internal_links.add(normalise(absolute))
        else:
            f.external_links.add(absolute)
    if soup.find("iframe", src=re.compile(r"google\.com/maps")):
        f.maps_link = True

    # Visible text
    for junk in soup(["script", "style", "noscript", "svg", "template"]):
        junk.decompose()
    body = soup.find("body") or soup
    f.text = " ".join(body.get_text(" ", strip=True).split())
    f.word_count = len(WORD.findall(f.text))
    for m in UK_PHONE.finditer(f.text):
        f.phones.add(_digits(m.group()))
    f.proof_points = len(NUMBER_PROOF.findall(f.text))

    # Answer-first: how long is the first paragraph after each H2?
    for h2 in body.find_all("h2"):
        p = h2.find_next(["p", "h2"])
        if p is not None and p.name == "p":
            f.first_paras.append(len(WORD.findall(p.get_text(" ", strip=True))))

    return f
