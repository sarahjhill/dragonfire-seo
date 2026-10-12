"""Run with: python manage.py test"""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from engine import ai_visibility
from engine.runner import run_audit

HOME = """<!DOCTYPE html><html lang="en-GB"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Electrician in Cardiff | Spark Sisters</title>
<meta name="description" content="Qualified female electricians in Cardiff. Rewires, EV chargers and safety checks, booked online in two minutes.">
<link rel="canonical" href="https://sparksisters.co.uk/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Electrician","name":"Spark Sisters",
"telephone":"029 2000 0000","url":"https://sparksisters.co.uk/","sameAs":["https://www.linkedin.com/x"]}</script>
</head><body><h1>Cardiff electricians</h1><h3>Skipped a level</h3>
<img src="/van.jpg"><a href="/about.html">About</a><a href="/missing.html">Gone</a>
<a href="tel:02920000000">Call</a></body></html>"""

ABOUT = """<!DOCTYPE html><html lang="en-GB"><head><title>About</title></head>
<body><h1>About</h1><h2>How much does a rewire cost?</h2><p>Most three-bed rewires in Cardiff cost between £4,000 and £6,500, depending on access.</p></body></html>"""


def make_site():
    d = Path(tempfile.mkdtemp())
    (d / "index.html").write_text(HOME)
    (d / "about.html").write_text(ABOUT)
    (d / "CNAME").write_text("sparksisters.co.uk")
    (d / "robots.txt").write_text("User-agent: *\nAllow: /\nUser-agent: PerplexityBot\nDisallow: /\n")
    return d


class EngineTests(TestCase):
    def setUp(self):
        self.r = run_audit(str(make_site()), brand="Spark Sisters", service="electrician",
                           towns=["Cardiff", "Newport"], ai=False)
        self.by_id = {f["id"]: f for f in self.r["findings"]}

    def test_reads_folder_and_cname(self):
        self.assertEqual(self.r["base_url"], "https://sparksisters.co.uk")
        self.assertEqual(len(self.r["pages"]), 2)

    def test_score_is_sane(self):
        self.assertTrue(0 <= self.r["score"] <= 100)
        self.assertIn(self.r["heat"], {"Inferno", "Blaze", "Smoulder", "Damp squib"})

    def test_catches_problems(self):
        self.assertEqual(self.by_id["sitemap"]["severity"], "fail")          # no sitemap
        self.assertEqual(self.by_id["alt"]["severity"], "fail")              # img with no alt
        self.assertEqual(self.by_id["heading-order"]["severity"], "warn")    # h1 -> h3
        self.assertEqual(self.by_id["ai-bots"]["severity"], "fail")          # PerplexityBot blocked
        self.assertEqual(self.by_id["town-newport"]["severity"], "fail")     # Newport never mentioned
        self.assertIn("broken", self.by_id)                                  # /missing.html

    def test_gives_credit(self):
        self.assertEqual(self.by_id["town-cardiff"]["severity"], "pass")
        self.assertEqual(self.by_id["phone"]["severity"], "pass")
        self.assertEqual(self.by_id["schema-home"]["severity"], "pass")

    def test_drafts_llms_txt(self):
        self.assertIn("# Spark Sisters", self.r["llms_txt"])


class AIVisibilityTests(TestCase):
    @mock.patch.dict("os.environ", {"PERPLEXITY_API_KEY": "x"}, clear=False)
    @mock.patch.dict(ai_visibility.PROVIDERS, {"Perplexity": ("PERPLEXITY_API_KEY",
                     lambda p: "Try Spark Sisters (sparksisters.co.uk) or volts.co.uk")})
    def test_detects_mentions_and_competitors(self):
        res = ai_visibility.run("Spark Sisters", "https://sparksisters.co.uk", "electrician", ["Cardiff"])
        self.assertTrue(res["ran"])
        self.assertEqual(res["share"], 100)
        self.assertIn("volts.co.uk", dict(res["competitors"]))


class ViewTests(TestCase):
    def test_full_flow(self):
        site = make_site()
        self.assertEqual(self.client.get(reverse("audits:home")).status_code, 200)
        resp = self.client.post(reverse("audits:home"), {
            "target": str(site), "brand": "Spark Sisters", "service": "electrician",
            "towns": "Cardiff", "max_pages": 10})
        self.assertEqual(resp.status_code, 302)
        page = self.client.get(resp.url)
        self.assertContains(page, "sparksisters.co.uk")
        self.assertContains(page, "Fix these")
        dl = self.client.get(resp.url + "download/")
        self.assertIn("attachment", dl["Content-Disposition"])
        self.assertEqual(self.client.get(reverse("audits:history")).status_code, 200)

    def test_private_hosts_refused(self):
        resp = self.client.post(reverse("audits:home"), {"target": "http://127.0.0.1", "max_pages": 5}, follow=True)
        self.assertContains(resp, "private address")


class FreeCheckTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.fake = run_audit(str(make_site()), brand="Spark Sisters", towns=["Cardiff"], ai=False)

    def post(self, **extra):
        data = {"website": "sparksisters.co.uk", "name": "Jo", "email": "jo@example.com",
                "business": "Spark Sisters", "service": "electrician", "town": "Cardiff", "consent": "on"}
        data.update(extra)
        with mock.patch("audits.views.run_audit", return_value=self.fake):
            return self.client.post(reverse("audits:free_check"), data)

    def test_creates_lead_and_shows_score(self):
        from .models import Lead
        resp = self.post()
        self.assertEqual(resp.status_code, 302)
        lead = Lead.objects.get()
        self.assertEqual(lead.email, "jo@example.com")
        self.assertIsNotNone(lead.audit)
        page = self.client.get(resp.url)
        self.assertContains(page, "Your top")
        self.assertContains(page, "on its way")

    def test_tips_optin_is_separate_and_off_by_default(self):
        from .models import Lead
        self.post()
        self.assertFalse(Lead.objects.get().newsletter_optin)
        Lead.objects.all().delete()
        from django.core.cache import cache
        cache.clear()
        self.post(tips="on")
        lead = Lead.objects.get()
        self.assertTrue(lead.newsletter_optin)
        self.assertIsNotNone(lead.newsletter_optin_at)

    def test_consent_required(self):
        from .models import Lead
        self.post(consent="")
        self.assertEqual(Lead.objects.count(), 0)

    def test_honeypot_drops_bots(self):
        from .models import Lead
        self.post(company_url="http://spam")
        self.assertEqual(Lead.objects.count(), 0)

    def test_rate_limit(self):
        from .models import Lead
        for _ in range(7):
            self.post()
        self.assertEqual(Lead.objects.count(), 5)

    @mock.patch("django.conf.settings.DRAGONFIRE_PUBLIC", True)
    def test_public_mode_locks_private_pages(self):
        self.assertEqual(self.client.get(reverse("audits:free_check")).status_code, 200)
        # private views are wrapped at import time, so check the wrapper exists via a fresh import
        import importlib

        from audits import views
        importlib.reload(views)
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        req = RequestFactory().get("/history/")
        req.user = AnonymousUser()
        self.assertEqual(views.history(req).status_code, 302)
        with mock.patch("django.conf.settings.DRAGONFIRE_PUBLIC", False):
            importlib.reload(views)
