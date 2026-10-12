"""
Every check the dragon runs.

Each check returns a Finding. Severity:
  fail  → FIX NOW   (costs you rankings or trust today)
  warn  → FIX SOON  (leaving heat on the table)
  pass  → NAILED IT
  info  → worth knowing, not scored

Copy rules (from POSITIONING.md): talk to "you", short lines, say the thing
everyone else softens, punch at the problem, never at the reader.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from urllib import robotparser
from urllib.parse import urlparse

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .page import PageFacts
from .sources import SiteSnapshot, normalise

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

CATEGORIES = {
    "technical": {"label": "Technical", "weight": 25,
                  "blurb": "Can Google get in, and is the place quick?"},
    "onpage": {"label": "On-page", "weight": 25,
               "blurb": "Does every page say clearly what it is?"},
    "schema": {"label": "Schema", "weight": 15,
               "blurb": "The behind-the-scenes ID card search engines read."},
    "local": {"label": "Local", "weight": 15,
              "blurb": "Will people nearby actually find you?"},
    "ai": {"label": "AI search", "weight": 20,
           "blurb": "Can ChatGPT, Claude and Perplexity understand and quote you?"},
}

AI_BOTS = {
    # name: (what it's for, is it a *search* bot that sends visitors?)
    "OAI-SearchBot": ("ChatGPT search results", True),
    "ChatGPT-User": ("ChatGPT reading your page when someone asks", True),
    "GPTBot": ("OpenAI model training", False),
    "Claude-SearchBot": ("Claude search results", True),
    "Claude-User": ("Claude reading your page when someone asks", True),
    "ClaudeBot": ("Anthropic model training", False),
    "PerplexityBot": ("Perplexity answers", True),
    "Google-Extended": ("Gemini training & grounding", False),
    "Applebot-Extended": ("Apple Intelligence", False),
}


@dataclass
class Finding:
    id: str
    category: str
    severity: str
    title: str
    detail: str = ""
    why: str = ""
    fix: str = ""
    pages: list = field(default_factory=list)
    weight: int = 2

    def as_dict(self):
        d = asdict(self)
        d["pages"] = [short(p) for p in self.pages][:25]
        d["more_pages"] = max(0, len(self.pages) - 25)
        return d


def short(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def plural(n, word, plural_word=None):
    return f"{n} {word if n == 1 else (plural_word or word + 's')}"


class Ctx:
    """Everything a check might need, worked out once."""

    def __init__(self, snap: SiteSnapshot, facts: list[PageFacts], towns: list[str],
                 brand: str, service: str):
        self.snap = snap
        self.facts = facts
        self.towns = [t.strip() for t in towns if t.strip()]
        self.brand = brand
        self.service = service
        self.home = next((f for f in facts if urlparse(f.url).path in ("", "/")), facts[0] if facts else None)
        self.indexable = [f for f in facts if not f.noindex]
        self.all_schema = [obj for f in facts for obj in f.jsonld]


# =========================================================================== #
# TECHNICAL
# =========================================================================== #
def check_robots(c: Ctx):
    r = c.snap.robots_txt
    if r is None:
        return Finding("robots", "technical", "fail", "No robots.txt",
                       "Search engines knock on /robots.txt first. Yours isn't there.",
                       "It's the bouncer's list. No list, and crawlers guess.",
                       "Add a robots.txt at the root:\n\nUser-agent: *\nAllow: /\n\nSitemap: "
                       f"{c.snap.base_url}/sitemap.xml", weight=3)
    rp = robotparser.RobotFileParser()
    rp.parse(r.splitlines())
    if not rp.can_fetch("Googlebot", c.snap.base_url + "/"):
        return Finding("robots", "technical", "fail", "robots.txt is blocking Google",
                       "Your robots.txt tells Google to stay out of the homepage.",
                       "This is the SEO equivalent of locking the shop and wondering where the customers went.",
                       "Remove the `Disallow: /` line for `User-agent: *` (or Googlebot).", weight=5)
    sev = "pass" if "sitemap:" in r.lower() else "warn"
    return Finding("robots", "technical", sev,
                   "robots.txt is open for business" if sev == "pass" else "robots.txt doesn't point to your sitemap",
                   "Crawlers are allowed in." + ("" if sev == "pass" else " But it doesn't tell them where the map is."),
                   "The Sitemap line saves crawlers hunting around.",
                   "" if sev == "pass" else f"Add this line to robots.txt:\n\nSitemap: {c.snap.base_url}/sitemap.xml",
                   weight=3)


def _sitemap_urls(xml: str) -> list[str]:
    soup = BeautifulSoup(xml, "html.parser")
    return [normalise(l.get_text(strip=True)) for l in soup.find_all("loc")]


def check_sitemap(c: Ctx):
    out = []
    if not c.snap.sitemap_xml:
        out.append(Finding("sitemap", "technical", "fail", "No sitemap.xml",
                           "There's no map of your site for search engines.",
                           "Without one, new pages can sit undiscovered for weeks.",
                           "Create sitemap.xml listing every page you want found, then submit it in Google Search Console.",
                           weight=3))
        return out
    listed = set(_sitemap_urls(c.snap.sitemap_xml))
    out.append(Finding("sitemap", "technical", "pass", "Sitemap found",
                       f"{plural(len(listed), 'URL')} listed.", weight=3))
    found = {f.url for f in c.indexable}
    missing = sorted(found - listed)
    ghosts = sorted(u for u in listed - found if urlparse(u).netloc == urlparse(c.snap.base_url).netloc)
    if missing:
        out.append(Finding("sitemap-missing", "technical", "warn",
                           f"{plural(len(missing), 'page')} missing from your sitemap",
                           "These pages are live and indexable but you haven't told Google about them.",
                           "Pages left off the map get found late, or not at all.",
                           "Add them to sitemap.xml — or add `noindex` if you don't want them in Google.",
                           pages=missing, weight=2))
    if ghosts and c.snap.mode == "folder":
        out.append(Finding("sitemap-ghosts", "technical", "warn",
                           f"Sitemap lists {plural(len(ghosts), 'page')} that don't exist",
                           "Your map points to rooms that aren't there.",
                           "Google wastes crawl time and trusts your sitemap less.",
                           "Remove these URLs from sitemap.xml or create the pages.", pages=ghosts, weight=2))
    noindexed = sorted(f.url for f in c.facts if f.noindex and f.url in listed)
    if noindexed:
        out.append(Finding("sitemap-noindex", "technical", "fail",
                           "Sitemap includes pages marked noindex",
                           "You're telling Google 'look here' and 'don't look here' at the same time.",
                           "Mixed signals make Google trust both less.",
                           "Take noindex pages out of sitemap.xml.", pages=noindexed, weight=2))
    return out


def check_404(c: Ctx):
    if c.snap.soft_404:
        return Finding("404", "technical", "fail", "Missing pages say '200 OK'",
                       "A made-up URL on your site returned a normal page instead of a 404.",
                       "Google can end up indexing junk URLs as real pages.",
                       "Make your host return a real 404 status for pages that don't exist.", weight=2)
    if c.snap.has_custom_404:
        return Finding("404", "technical", "pass", "Custom 404 page", "Lost visitors get a way back.", weight=1)
    return Finding("404", "technical", "warn", "No custom 404 page",
                   "Mistyped links land on a generic error.",
                   "A dead end is where visitors leave.",
                   "Add a 404.html with your branding and links to your main pages.", weight=1)


def check_broken_links(c: Ctx):
    broken = c.snap.broken_links
    if not broken:
        return Finding("broken", "technical", "pass", "No broken internal links",
                       "Every internal link goes somewhere real.", weight=3)
    pages = [f"{short(t)}  ← linked from {', '.join(short(p) for p in sorted(set(src))[:3]) or 'sitemap'}"
             for t, src in sorted(broken.items())]
    if c.snap.mode == "folder":
        return Finding("broken", "technical", "warn",
                       f"{plural(len(broken), 'link')} point to pages outside this folder",
                       "These addresses are on your domain but there's no matching file here.",
                       "If they're served from another project (say, a separate GitHub Pages repo), "
                       "you're fine. If not, they're broken — and broken links leak trust.",
                       "Click each one on the live site. Run a live torch to check them automatically.",
                       pages=pages, weight=1)
    return Finding("broken", "technical", "fail", f"{plural(len(broken), 'broken link')}",
                   "Links on your site that go nowhere.",
                   "Broken links leak trust — with visitors and with Google.",
                   "Fix the link or create the missing page.", pages=pages, weight=3)


def check_https(c: Ctx):
    if not c.snap.base_url.startswith("https://"):
        return Finding("https", "technical", "fail", "Site isn't on HTTPS",
                       "Browsers show 'Not secure' next to your name.",
                       "That's the opposite of being taken seriously.",
                       "Turn on HTTPS at your host (free with Let's Encrypt / most hosts).", weight=4)
    if c.snap.https_redirect is False:
        return Finding("https", "technical", "warn", "http:// doesn't redirect to https://",
                       "The insecure version of your site still loads.",
                       "Two copies of every page split your ranking power.",
                       "Turn on 'force HTTPS' at your host.", weight=3)
    insecure = [f.url for f in c.facts if f.canonical and f.canonical.startswith("http://")]
    if insecure:
        return Finding("https", "technical", "warn", "Canonical tags point to http://",
                       "Your pages call their insecure twin the 'real' one.", "",
                       "Change canonical URLs to https://.", pages=insecure, weight=3)
    return Finding("https", "technical", "pass", "HTTPS everywhere", "Padlock on. Good.", weight=4)


def check_page_weight(c: Ctx):
    heavy = [(f.url, f.html_bytes) for f in c.facts if f.html_bytes > 150_000]
    if not heavy:
        return Finding("weight", "technical", "pass", "HTML is lean",
                       "No page's HTML is over 150 KB.", weight=1)
    worst = max(b for _, b in heavy)
    return Finding("weight", "technical", "fail" if worst > 300_000 else "warn",
                   "Heavy HTML", "Some pages ship a lot of code before anything else loads.",
                   "Big HTML is slow on a phone with one bar of signal on a building site.",
                   "Move inline styles/scripts into files, and cut unused markup.",
                   pages=[f"{short(u)} — {b // 1024} KB" for u, b in heavy], weight=1)


def check_render_blocking(c: Ctx):
    out = []
    blockers = [f for f in c.facts if f.blocking_scripts]
    if blockers:
        out.append(Finding("blocking-js", "technical", "warn", "Scripts are blocking your page",
                           "JavaScript in the <head> without `defer` freezes the page until it downloads.",
                           "Every frozen second, someone hits back.",
                           "Add `defer` to <script src> tags in the <head>, or move them to the end of <body>.",
                           pages=[f"{short(f.url)} — {f.blocking_scripts}" for f in blockers], weight=2))
    many_css = [f for f in c.facts if f.stylesheets > 5]
    if many_css:
        worst = max(f.stylesheets for f in many_css)
        out.append(Finding("css-count", "technical", "warn",
                           f"Up to {worst} stylesheets per page",
                           f"Your pages load as many as {worst} separate CSS files before showing anything.",
                           "Each one is another trip to the server before the first paint — painful on mobile.",
                           "Bundle them into one file for production (a tiny build script can concatenate them).",
                           pages=[f"{short(f.url)} — {f.stylesheets} files" for f in many_css], weight=2))
    if not out:
        out.append(Finding("blocking", "technical", "pass", "Nothing blocking the first paint",
                           "Scripts are deferred and CSS is tidy.", weight=2))
    return out


def check_images(c: Ctx):
    out = []
    sizes = c.snap.asset_sizes
    heavy = sorted({(i["src"], sizes[i["src"]]) for f in c.facts for i in f.images
                    if sizes.get(i["src"], 0) > 300_000}, key=lambda x: -x[1])
    if heavy:
        worst = heavy[0][1]
        out.append(Finding("img-weight", "technical", "fail" if worst > 1_000_000 else "warn",
                           f"{plural(len(heavy), 'heavy image')}",
                           "Images over 300 KB. Biggest is " + f"{worst // 1024} KB.",
                           "Images are the #1 reason small-business sites are slow.",
                           "Resize to the size it's shown at, and export as WebP or AVIF (squoosh.app is free).",
                           pages=[f"{short(s)} — {b // 1024} KB" for s, b in heavy], weight=3))
    elif sizes:
        out.append(Finding("img-weight", "technical", "pass", "Images are a sensible weight",
                           f"Checked {plural(len(sizes), 'image')}. None over 300 KB.", weight=3))
    unsized = sorted({f.url for f in c.facts for i in f.images if not i["sized"]})
    if unsized:
        n = sum(1 for f in c.facts for i in f.images if not i["sized"])
        out.append(Finding("img-size", "technical", "warn", f"{plural(n, 'image')} without width/height",
                           "The page jumps around as images load.",
                           "Google measures that jump (CLS). So do annoyed thumbs.",
                           'Add width="" and height="" to every <img> (the real pixel size — CSS can still resize it).',
                           pages=unsized, weight=1))
    no_lazy = [f.url for f in c.facts if len(f.images) > 3 and not any(i["lazy"] for i in f.images)]
    if no_lazy:
        out.append(Finding("img-lazy", "technical", "warn", "Images all load at once",
                           "Pages with lots of images load every one up front, even ones nobody scrolls to.",
                           "Wasted data and a slower first screen.",
                           'Add loading="lazy" to images below the first screen.', pages=no_lazy, weight=1))
    return out


def check_speed(c: Ctx):
    timed = [f for f in c.facts if f.elapsed_ms is not None]
    if not timed:
        return []
    slow = [f for f in timed if f.elapsed_ms > 1500]
    avg = sum(f.elapsed_ms for f in timed) // len(timed)
    if slow:
        return Finding("ttfb", "technical", "warn", "Slow server responses",
                       f"Average response {avg} ms. Some pages took over 1.5 s just to start.",
                       "People decide in three seconds. Don't spend two of them waiting for the server.",
                       "Check your hosting plan, turn on caching, or move to a CDN-backed host.",
                       pages=[f"{short(f.url)} — {f.elapsed_ms} ms" for f in slow], weight=2)
    return Finding("ttfb", "technical", "pass", "Server responds fast", f"Average {avg} ms.", weight=2)


# =========================================================================== #
# ON-PAGE
# =========================================================================== #
def check_titles(c: Ctx):
    out = []
    missing = [f.url for f in c.indexable if not f.title]
    if missing:
        out.append(Finding("title-missing", "onpage", "fail", "Pages with no title",
                           "The title is the blue link in Google. These pages don't have one.",
                           "No title, no click.", "Add a <title> to each page: what it is | your name, place.",
                           pages=missing, weight=4))
    bad_len = [f"{short(f.url)} — {len(f.title)} chars: “{f.title}”" for f in c.indexable
               if f.title and not 30 <= len(f.title) <= 60]
    if bad_len:
        out.append(Finding("title-length", "onpage", "warn", "Titles too short or too long",
                           "Aim for 30–60 characters. Longer gets cut off with '…' in Google.",
                           "The cut-off bit is usually the bit that sells.",
                           "Lead with what you do and where. Brand goes last.", pages=bad_len, weight=2))
    dupes = [t for t, n in Counter(f.title for f in c.indexable if f.title).items() if n > 1]
    if dupes:
        out.append(Finding("title-dupes", "onpage", "warn", "Duplicate titles",
                           "Different pages, same title. Google can't tell them apart either.", "",
                           "Give each page its own title.",
                           pages=[f"“{t}”" for t in dupes], weight=2))
    if not out:
        out.append(Finding("titles", "onpage", "pass", "Titles are sharp",
                           "Every page has a unique title of a sensible length.", weight=4))
    return out


def check_descriptions(c: Ctx):
    out = []
    missing = [f.url for f in c.indexable if not f.description]
    if missing:
        out.append(Finding("desc-missing", "onpage", "fail", "Pages with no meta description",
                           "Google will grab random text off the page instead.",
                           "That snippet is your shop window. Don't let Google dress it.",
                           "Write a 120–155 character description: who it's for, what they get, why you.",
                           pages=missing, weight=3))
    bad = [f"{short(f.url)} — {len(f.description)} chars" for f in c.indexable
           if f.description and not 70 <= len(f.description) <= 160]
    if bad:
        out.append(Finding("desc-length", "onpage", "warn", "Descriptions the wrong length",
                           "70–160 characters is the sweet spot.", "",
                           "Trim long ones; beef up short ones.", pages=bad, weight=1))
    dupes = [d for d, n in Counter(f.description for f in c.indexable if f.description).items() if n > 1]
    if dupes:
        out.append(Finding("desc-dupes", "onpage", "warn", "Duplicate meta descriptions",
                           "Copy-paste descriptions make your pages look interchangeable.", "",
                           "Write one per page.", pages=[d[:80] + "…" for d in dupes], weight=1))
    if not out:
        out.append(Finding("descriptions", "onpage", "pass", "Meta descriptions done properly",
                           "Every page has its own, at a good length.", weight=3))
    return out


def check_h1(c: Ctx):
    none = [f.url for f in c.indexable if not f.h1s]
    many = [f"{short(f.url)} — {len(f.h1s)} H1s" for f in c.indexable if len(f.h1s) > 1]
    out = []
    if none:
        out.append(Finding("h1-missing", "onpage", "fail", "Pages with no H1",
                           "The H1 is the headline Google reads first. These pages skip it.", "",
                           "Give every page one H1 that says what the page is about.", pages=none, weight=3))
    if many:
        out.append(Finding("h1-many", "onpage", "warn", "More than one H1",
                           "Two headlines fighting for top billing.",
                           "It muddies what the page is actually about.",
                           "Keep one H1. Make the rest H2s.", pages=many, weight=1))
    if not out:
        out.append(Finding("h1", "onpage", "pass", "One clear H1 per page", "", weight=3))
    return out


def check_heading_order(c: Ctx):
    skips = []
    for f in c.indexable:
        prev = 0
        for level, text in f.headings:
            if prev and level > prev + 1:
                skips.append(f"{short(f.url)} — H{prev} → H{level} (“{text[:40]}”)")
                break
            prev = level
    if skips:
        return Finding("heading-order", "onpage", "warn", "Headings skip levels",
                       "Jumping from H2 to H4 is like a contents page with missing chapters.",
                       "Screen readers and AI both use headings to understand structure.",
                       "Use headings in order: H1 → H2 → H3. Style them with CSS, not by picking a smaller tag.",
                       pages=skips, weight=1)
    return Finding("heading-order", "onpage", "pass", "Headings in a sensible order", "", weight=1)


def check_basics(c: Ctx):
    out = []
    no_lang = [f.url for f in c.facts if not f.lang]
    no_vp = [f.url for f in c.facts if not f.has_viewport]
    no_canon = [f.url for f in c.indexable if not f.canonical]
    if no_lang:
        out.append(Finding("lang", "onpage", "warn", "Missing language tag",
                           "Pages don't say what language they're in.", "",
                           'Add lang="en-GB" to the <html> tag.', pages=no_lang, weight=1))
    if no_vp:
        out.append(Finding("viewport", "onpage", "fail", "Not set up for phones",
                           "No viewport tag — phones show a shrunk desktop page.",
                           "Google ranks the mobile version of your site. This is that version.",
                           '<meta name="viewport" content="width=device-width, initial-scale=1">',
                           pages=no_vp, weight=4))
    if no_canon:
        out.append(Finding("canonical", "onpage", "warn", "No canonical tag",
                           "These pages don't say which URL is the 'real' one.",
                           "Tracking links and ?query versions can split your ranking.",
                           '<link rel="canonical" href="https://yoursite.com/this-page/">',
                           pages=no_canon, weight=2))
    if not out:
        out.append(Finding("basics", "onpage", "pass", "Language, mobile and canonical tags all set", "",
                           weight=3))
    return out


def check_alt(c: Ctx):
    missing = [(f.url, i["src"]) for f in c.facts for i in f.images if i["alt"] is None]
    total = sum(len(f.images) for f in c.facts)
    if not total:
        return []
    if missing:
        return Finding("alt", "onpage", "fail" if len(missing) / total > 0.2 else "warn",
                       f"{plural(len(missing), 'image')} with no alt text",
                       f"{len(missing)} of {total} images have no alt attribute at all.",
                       "Blind visitors hear 'image'. Google sees nothing. Both are customers.",
                       'Describe what the image shows: alt="Sarah fitting a consumer unit". '
                       'Decorative images get alt="" (empty, but present).',
                       pages=[f"{short(u)} — {short(s)}" for u, s in missing], weight=2)
    return Finding("alt", "onpage", "pass", "Every image has alt text", f"All {total} covered.", weight=2)


def check_thin(c: Ctx):
    thin = [f"{short(f.url)} — {f.word_count} words" for f in c.indexable if f.word_count < 300]
    if thin:
        return Finding("thin", "onpage", "warn", f"{plural(len(thin), 'thin page')}",
                       "Under 300 words. Google — and AI — have little to go on.",
                       "A page with nothing to say doesn't get shown to anyone.",
                       "Add the questions customers actually ask, real examples, prices or process.",
                       pages=thin, weight=2)
    return Finding("thin", "onpage", "pass", "Pages have real substance", "Every indexable page has 300+ words.",
                   weight=2)


def check_social(c: Ctx):
    bad = [f.url for f in c.indexable if not (f.og.get("og:title") and f.og.get("og:image"))]
    if bad:
        return Finding("social", "onpage", "warn", "Links look bare when shared",
                       "No Open Graph title/image, so WhatsApp, LinkedIn and Facebook show a plain link.",
                       "A shared link with no picture gets scrolled past.",
                       "Add og:title, og:description, og:image (1200×630) and twitter:card.",
                       pages=bad, weight=1)
    return Finding("social", "onpage", "pass", "Share cards on every page",
                   "Links show a proper preview when shared.", weight=1)


def check_internal_linking(c: Ctx):
    out = []
    inbound = defaultdict(int)
    for f in c.facts:
        for l in f.internal_links:
            if l != f.url:
                inbound[l] += 1
    orphans = [f.url for f in c.indexable if f is not c.home and inbound.get(f.url, 0) == 0]
    if orphans:
        out.append(Finding("orphans", "onpage", "warn", f"{plural(len(orphans), 'orphan page')}",
                           "No other page on your site links to these.",
                           "If you don't point at a page, Google assumes it doesn't matter.",
                           "Link to them from your homepage, footer or related pages.", pages=orphans, weight=2))
    weak = [f"{short(f.url)} — {len(f.internal_links)}" for f in c.indexable if len(f.internal_links) < 3]
    if weak:
        out.append(Finding("dead-ends", "onpage", "warn", "Dead-end pages",
                           "Pages with fewer than 3 links to anywhere else on your site.", "",
                           "Add a 'what next' — related work, contact, services.", pages=weak, weight=1))
    if not out:
        out.append(Finding("linking", "onpage", "pass", "Pages are well connected", "", weight=2))
    return out


# =========================================================================== #
# SCHEMA
# =========================================================================== #
LOCAL_TYPES = {"LocalBusiness", "ProfessionalService", "HomeAndConstructionBusiness", "Electrician",
               "Plumber", "HVACBusiness", "RoofingContractor", "GeneralContractor", "HousePainter",
               "Locksmith", "MovingCompany", "HealthAndBeautyBusiness", "Store", "FoodEstablishment",
               "Restaurant", "LegalService", "AccountingService", "FinancialService", "MedicalBusiness",
               "AutomotiveBusiness", "EmploymentAgency", "ChildCare", "SportsActivityLocation"}


def _business(c: Ctx):
    if not c.home:
        return None
    for obj in c.home.jsonld:
        t = obj.get("@type")
        types = set(t if isinstance(t, list) else [t])
        if types & LOCAL_TYPES:
            return obj
    for obj in c.home.jsonld:
        if obj.get("@type") in ("Organization", "Corporation", "Person"):
            return obj
    return None


def check_schema_present(c: Ctx):
    out = []
    errors = [f.url for f in c.facts if f.jsonld_errors]
    if errors:
        out.append(Finding("schema-errors", "schema", "fail", "Broken structured data",
                           "Some JSON-LD blocks won't parse. Search engines ignore them entirely.", "",
                           "Paste the block into validator.schema.org and fix the error (usually a stray comma).",
                           pages=errors, weight=3))
    if not c.home or not c.home.jsonld:
        out.append(Finding("schema-home", "schema", "fail", "No structured data on your homepage",
                           "Nothing tells Google, in its own language, who you are, what you do and where.",
                           "Schema is how you get the rich results — and how AI tools get their facts straight.",
                           "Add a LocalBusiness (or ProfessionalService) JSON-LD block to your homepage.", weight=5))
        return out
    without = [f.url for f in c.indexable if not f.jsonld]
    out.append(Finding("schema-home", "schema", "pass", "Homepage has structured data",
                       "Found: " + ", ".join(sorted(c.home.schema_types)) + ".", weight=5))
    if without:
        out.append(Finding("schema-pages", "schema", "warn", "Pages with no structured data",
                           "These pages don't describe themselves to search engines.", "",
                           "Add WebPage / Service / Article schema as appropriate.", pages=without, weight=1))
    return out


def check_business_schema(c: Ctx):
    biz = _business(c)
    if biz is None:
        if c.home and c.home.jsonld:
            return Finding("schema-biz", "schema", "fail", "No business schema",
                           "Your homepage has schema, but none of it says 'this is a business'.", "",
                           "Add a LocalBusiness / ProfessionalService block.", weight=4)
        return []
    t = biz.get("@type")
    is_local = bool(set(t if isinstance(t, list) else [t]) & LOCAL_TYPES)
    wanted = {
        "telephone": "phone number", "address": "address (region + postcode is fine for service-area businesses)",
        "areaServed": "areas you serve", "sameAs": "links to your profiles (LinkedIn, Google, Instagram…)",
        "openingHoursSpecification": "opening hours", "geo": "map coordinates", "logo": "logo", "image": "photo",
        "priceRange": "price range", "url": "website URL", "description": "description",
    }
    have_hours = biz.get("openingHoursSpecification") or biz.get("openingHours")
    founder_same = isinstance(biz.get("founder"), dict) and biz["founder"].get("sameAs")
    missing = [label for key, label in wanted.items()
               if not (biz.get(key) or (key == "openingHoursSpecification" and have_hours)
                       or (key == "sameAs" and founder_same))]
    critical = [m for m in missing if m.startswith(("phone", "address"))]
    if not is_local:
        sev, title = "warn", f"Business schema is a generic {t}"
    elif critical:
        sev, title = "warn", "Business schema is missing the basics"
    elif missing:
        sev, title = "warn", "Business schema could be fuller"
    else:
        sev, title = "pass", "Business schema is complete"
    return Finding("schema-biz", "schema", sev, title,
                   f"Type: {t}." + (" Missing: " + "; ".join(missing) + "." if missing else ""),
                   "Google's local results and AI answers lean on exactly these fields. "
                   "Phone and address carry the most weight." if missing else "",
                   "Add the missing fields to the JSON-LD block on your homepage." if missing else "",
                   weight=4)


def check_faq_schema(c: Ctx):
    types = {t for f in c.facts for t in f.schema_types}
    if "FAQPage" in types:
        return Finding("schema-faq", "schema", "pass", "FAQ schema in place",
                       "Your Q&As are machine-readable.", weight=2)
    return Finding("schema-faq", "schema", "warn", "No FAQ schema",
                   "You don't mark up any questions and answers.",
                   "Google rarely shows FAQ rich results any more — but structured Q&A is still the easiest "
                   "thing for AI assistants to lift and quote.",
                   "Add a short FAQ section to key pages and wrap it in FAQPage JSON-LD.", weight=2)


def check_breadcrumbs(c: Ctx):
    inner = [f for f in c.indexable if f is not c.home]
    if not inner:
        return []
    without = [f.url for f in inner if "BreadcrumbList" not in f.schema_types]
    if not without:
        return Finding("schema-crumbs", "schema", "pass", "Breadcrumbs marked up", "", weight=1)
    return Finding("schema-crumbs", "schema", "warn", "No breadcrumb schema on inner pages",
                   "Google shows a tidy 'site › section' trail instead of a raw URL when you add these.", "",
                   "Add BreadcrumbList JSON-LD (Home › This page) to inner pages.", pages=without, weight=1)


# =========================================================================== #
# LOCAL
# =========================================================================== #
def check_towns(c: Ctx):
    if not c.towns:
        return Finding("towns", "local", "info", "No towns given",
                       "Add the towns you work in to check local targeting.", weight=0)
    out = []
    for town in c.towns:
        rx = re.compile(rf"\b{re.escape(town)}\b", re.I)
        prime = [f.url for f in c.indexable
                 if rx.search(f.title or "") or any(rx.search(h) for h in f.h1s)]
        body = [f.url for f in c.indexable if rx.search(f.text)]
        if prime:
            out.append(Finding(f"town-{town.lower()}", "local", "pass", f"{town}: in your titles/headlines",
                               f"Prime position on {plural(len(prime), 'page')}.", pages=prime, weight=3))
        elif body:
            out.append(Finding(f"town-{town.lower()}", "local", "warn", f"{town}: buried in body text",
                               f"{town} is mentioned, but never in a page title or H1.",
                               f"Someone searching '{c.service or 'your service'} {town}' needs to see {town} "
                               "in the blue link.",
                               f"Put {town} in the title and H1 of a page built for {town}.", weight=3))
        else:
            out.append(Finding(f"town-{town.lower()}", "local", "fail", f"{town}: not mentioned at all",
                               f"Nothing on your site says you work in {town}.",
                               "Google won't guess.", f"Create a page for {town} customers.", weight=3))
    return out


def check_location_pages(c: Ctx):
    if len(c.towns) < 2:
        return []
    missing = []
    for town in c.towns:
        slug = re.sub(r"\W+", "-", town.lower())
        rx = re.compile(rf"\b{re.escape(town)}\b", re.I)
        has = any(slug in urlparse(f.url).path.lower() or
                  (rx.search(f.title or "") and f is not c.home) for f in c.indexable)
        if not has:
            missing.append(town)
    if missing:
        return Finding("location-pages", "local", "warn",
                       f"No dedicated page for {', '.join(missing)}",
                       f"You serve {', '.join(c.towns)} — but one homepage can't rank in all of them at once.",
                       "Location pages are the single biggest local SEO lever for service businesses.",
                       f"Make a page per town (e.g. /{re.sub(r'[^a-z]+', '-', missing[0].lower())}/) "
                       "with local proof: jobs done there, local reviews, areas covered. Not a copy-paste with "
                       "the town swapped — Google spots those.", weight=3)
    return Finding("location-pages", "local", "pass", "A page for every town", "", weight=3)


def check_phone(c: Ctx):
    tel = [f for f in c.facts if f.tel_links]
    phones = {p for f in c.facts for p in f.phones}
    out = []
    if not phones:
        out.append(Finding("phone", "local", "warn", "No phone number anywhere",
                           "Customers can't ring you from the site.",
                           "Local search leans on a consistent name, address and phone (NAP). And plenty of "
                           "customers would rather ring than fill in a form.",
                           "Add a tap-to-call link: <a href=\"tel:+442900000000\">029 0000 0000</a>. "
                           "A business line or virtual number is fine if you don't want your mobile out there.",
                           weight=3))
    elif not tel:
        out.append(Finding("phone", "local", "warn", "Phone number isn't tap-to-call",
                           "Your number is on the page, but phones can't dial it with a tap.", "",
                           "Wrap it in <a href=\"tel:…\">.", weight=2))
    else:
        out.append(Finding("phone", "local", "pass", "Tap-to-call phone number", "", weight=3))
    if len(phones) > 1:
        out.append(Finding("nap", "local", "warn", "More than one phone number",
                           "Found: " + ", ".join(sorted(phones)) + ".",
                           "Inconsistent details make Google less sure you're one real business.",
                           "Use one number everywhere — site, schema, Google Business Profile, directories.",
                           weight=2))
    return out


def check_gbp(c: Ctx):
    same = []
    for obj in c.all_schema:
        s = obj.get("sameAs") or []
        same.extend(s if isinstance(s, list) else [s])
    gbp = any(f.maps_link for f in c.facts) or any(
        any(k in str(x) for k in ("google.com/maps", "g.page", "maps.app.goo.gl", "share.google")) for x in same)
    if gbp:
        return Finding("gbp", "local", "pass", "Linked to your Google Business Profile", "", weight=3)
    return Finding("gbp", "local", "warn", "No link to a Google Business Profile",
                   "No Google Maps / Business Profile link found on the site or in schema.",
                   "Your Business Profile is what shows in the map pack — the top of local results. "
                   "Linking site ↔ profile ties them together.",
                   "Claim your free profile at business.google.com (service-area businesses can hide the address), "
                   "then link to it from your footer and add it to `sameAs` in your schema.", weight=3)


def check_reviews(c: Ctx):
    types = {t for f in c.facts for t in f.schema_types}
    words = any(re.search(r"\b(testimonial|review|★|rated)\b", f.text, re.I) for f in c.facts)
    if {"Review", "AggregateRating"} & types:
        return Finding("reviews", "local", "pass", "Reviews marked up", "", weight=2)
    if words:
        return Finding("reviews", "local", "warn", "Reviews aren't marked up",
                       "You've got testimonials, but search engines can't read them as reviews.", "",
                       "Collect reviews on your Google Business Profile, and show real ones on site. "
                       "(Only mark up reviews of your business that customers genuinely left.)", weight=2)
    return Finding("reviews", "local", "warn", "No reviews or testimonials",
                   "No social proof found on the site.",
                   "Strangers trust strangers who've already trusted you.",
                   "Ask your last 5 happy customers for a Google review this week. Put the best ones on your site.",
                   weight=2)


# =========================================================================== #
# AI SEARCH (GEO / AEO)
# =========================================================================== #
def check_llms_txt(c: Ctx):
    if c.snap.llms_txt:
        return Finding("llms", "ai", "pass", "llms.txt in place",
                       "You've left AI tools a plain-English summary of your site.", weight=1)
    return Finding("llms", "ai", "warn", "No llms.txt",
                   "llms.txt is a new, plain-text 'about this site' file for AI tools.",
                   "Honest truth: it's early and not every AI reads it yet. But it's ten minutes of work "
                   "and it's how you'd want to be summarised.",
                   "Add /llms.txt: a # heading with your name, a one-line summary, then links to your key "
                   "pages with a sentence each. Dragonfire drafts one for you below.", weight=1)


def check_ai_bots(c: Ctx):
    r = c.snap.robots_txt
    if r is None:
        return Finding("ai-bots", "ai", "info", "AI crawlers: no robots.txt to read", weight=0)
    rp = robotparser.RobotFileParser()
    rp.parse(r.splitlines())
    blocked_search = [b for b, (_, search) in AI_BOTS.items() if search and not rp.can_fetch(b, c.snap.base_url + "/")]
    blocked_train = [b for b, (_, search) in AI_BOTS.items() if not search and not rp.can_fetch(b, c.snap.base_url + "/")]
    if blocked_search:
        return Finding("ai-bots", "ai", "fail", "You're blocking AI search engines",
                       "robots.txt shuts out: " + ", ".join(blocked_search) + ".",
                       "These bots fetch pages to answer people's questions live. Block them and you can't be "
                       "recommended.",
                       "Remove the Disallow rules for these user-agents. (Blocking *training* bots like GPTBot "
                       "is a separate choice — that's fine either way.)", weight=4)
    note = (" Training bots blocked: " + ", ".join(blocked_train) + " — that's your call and doesn't stop you "
            "appearing in AI search.") if blocked_train else ""
    return Finding("ai-bots", "ai", "pass", "AI search crawlers are welcome",
                   "ChatGPT, Claude and Perplexity's search bots can all read your site." + note, weight=4)


def check_questions(c: Ctx):
    qs = [(f.url, h) for f in c.indexable for lvl, h in f.headings if lvl >= 2 and h.strip().endswith("?")]
    if len(qs) >= 5:
        return Finding("questions", "ai", "pass", "Headings ask real questions",
                       f"{plural(len(qs), 'question-shaped heading')} across the site.", weight=3)
    return Finding("questions", "ai", "warn" if qs else "fail",
                   "Too few question-shaped headings" if qs else "No headings are questions",
                   f"Found {len(qs)}. People ask AI full questions: 'how much does a website cost for an "
                   "electrician?'",
                   "When your heading IS the question, you become the obvious paragraph to quote.",
                   "Add H2s phrased the way customers ask, each followed by a 40–60 word straight answer.",
                   pages=[f"{short(u)} — {h}" for u, h in qs], weight=3)


def check_answer_first(c: Ctx):
    paras = [n for f in c.indexable for n in f.first_paras]
    if len(paras) < 3:
        return []
    good = sum(1 for n in paras if 12 <= n <= 80)
    share = good / len(paras)
    if share >= 0.6:
        return Finding("answer-first", "ai", "pass", "Sections lead with the answer",
                       f"{int(share * 100)}% of sections open with a quotable 12–80 word paragraph.", weight=2)
    return Finding("answer-first", "ai", "warn", "Sections don't lead with the answer",
                   f"Only {int(share * 100)}% of H2 sections start with a short, quotable paragraph.",
                   "AI engines lift the first clean paragraph after a heading. Make it the answer, "
                   "not a warm-up.",
                   "Under each H2, open with one 1–3 sentence direct answer. Then the detail.", weight=2)


def check_proof(c: Ctx):
    if not c.home:
        return []
    n = c.home.proof_points
    if n >= 3:
        return Finding("proof", "ai", "pass", "Homepage backs itself up with numbers",
                       f"{plural(n, 'hard number')} found (%, £, years, jobs…).", weight=2)
    return Finding("proof", "ai", "warn", "Homepage is light on hard numbers",
                   f"Found {n}. Claims without numbers are just vibes.",
                   "Specific facts — '47 sites built', '3-day turnaround', 'from £450' — are what AI "
                   "repeats and humans believe.",
                   "Add 3+ concrete numbers to your homepage: prices, turnaround, jobs done, years.", weight=2)


def check_freshness(c: Ctx):
    dated = [f for f in c.indexable if f.has_date]
    authored = [f for f in c.indexable if f.has_author]
    out = []
    if not dated:
        out.append(Finding("fresh", "ai", "warn", "Nothing on the site is dated",
                           "No published/updated dates in schema, <time> tags or meta.",
                           "AI tools and Google prefer content they can see is current.",
                           'Add dateModified to your schema, and show "Updated October 2026" on key pages.',
                           weight=2))
    else:
        out.append(Finding("fresh", "ai", "pass", "Content carries dates",
                           f"{plural(len(dated), 'page')} show when they were written or updated.", weight=2))
    if len(authored) < max(1, len(c.indexable) // 2):
        out.append(Finding("author", "ai", "warn", "Most pages don't say who wrote them",
                           f"Only {len(authored)} of {len(c.indexable)} pages name an author.",
                           "Real, named expertise is what both Google and AI trust.", "",
                           pages=[f.url for f in c.indexable if not f.has_author], weight=1))
    return out


def check_content_hub(c: Ctx):
    hub = [f.url for f in c.indexable if re.search(r"/(blog|guides?|insights|articles|news|learn|resources)/",
                                                   urlparse(f.url).path + "/", re.I)
           or {"Article", "BlogPosting", "NewsArticle", "HowTo"} & f.schema_types]
    if len(hub) >= 3:
        return Finding("hub", "ai", "pass", "You publish articles",
                       f"{plural(len(hub), 'article/guide page')} found.", pages=hub, weight=3)
    return Finding("hub", "ai", "fail" if not hub else "warn",
                   "No articles for AI to quote" if not hub else "Only a couple of articles",
                   "AI assistants answer questions. If you've never answered one in writing, you're not in "
                   "the running.",
                   "Every article is another door into your site — for Google and for ChatGPT.",
                   "Start a /guides/ section. One honest, specific article a fortnight beats 30 AI-spun ones a month. "
                   "Dragonfire suggests topics below.", pages=hub, weight=3)


def check_entity(c: Ctx):
    same = set()
    for obj in c.all_schema:
        s = obj.get("sameAs") or []
        same.update(s if isinstance(s, list) else [s])
    if len(same) >= 3:
        return Finding("entity", "ai", "pass", "You're a well-connected entity",
                       f"{plural(len(same), 'profile')} linked via sameAs.", weight=2)
    return Finding("entity", "ai", "warn", "AI can't easily connect the dots on you",
                   f"Only {plural(len(same), 'profile link')} in your schema's sameAs.",
                   "sameAs is how machines confirm the Sarah on LinkedIn is the Sarah on this site. "
                   "More confirmed profiles = more confidence to recommend you.",
                   "List your LinkedIn, Google Business Profile, Instagram, GitHub, Companies House page etc. in sameAs.",
                   weight=2)


ALL_CHECKS = [
    check_robots, check_sitemap, check_404, check_broken_links, check_https, check_page_weight,
    check_render_blocking, check_images, check_speed,
    check_titles, check_descriptions, check_h1, check_heading_order, check_basics, check_alt, check_thin,
    check_social, check_internal_linking,
    check_schema_present, check_business_schema, check_faq_schema, check_breadcrumbs,
    check_towns, check_location_pages, check_phone, check_gbp, check_reviews,
    check_llms_txt, check_ai_bots, check_questions, check_answer_first, check_proof, check_freshness,
    check_content_hub, check_entity,
]


def run_checks(ctx: Ctx) -> list[Finding]:
    out = []
    for check in ALL_CHECKS:
        result = check(ctx)
        if result is None:
            continue
        out.extend(result if isinstance(result, list) else [result])
    return out
