"""
Torch a site from the terminal.

    python manage.py torch https://sarahjhill.com --brand "Sarah J Hill" \
        --service "web designer for tradeswomen" --towns "Cardiff, Birmingham"

    python manage.py torch ~/Documents/vscode-projects/sarahjhill-redesign --no-ai

Saves the audit (so it shows in the web app) and writes a standalone HTML
report into reports/.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.utils.text import slugify

from audits.views import save_audit
from engine.runner import run_audit

FLAME, AMBER, DIM, BOLD, RESET = "\033[38;5;202m", "\033[38;5;214m", "\033[2m", "\033[1m", "\033[0m"
SEV = {"fail": f"{FLAME}FIX NOW {RESET}", "warn": f"{AMBER}FIX SOON{RESET}", "pass": f"{DIM}NAILED IT{RESET}"}


class Command(BaseCommand):
    help = "Run a Dragonfire SEO audit on a website URL or a local folder."

    def add_arguments(self, parser):
        parser.add_argument("target", help="URL (sarahjhill.com) or folder path")
        parser.add_argument("--brand", default="")
        parser.add_argument("--service", default="", help='e.g. "electrician"')
        parser.add_argument("--towns", default="", help='comma-separated, e.g. "Cardiff, Newport"')
        parser.add_argument("--max-pages", type=int, default=40)
        parser.add_argument("--base-url", default=None, help="Public URL for a folder audit (default: from CNAME)")
        parser.add_argument("--no-ai", action="store_true", help="Skip asking the AIs")
        parser.add_argument("--out", default=None, help="Where to write the HTML report")

    def handle(self, *args, **o):
        self.stdout.write(f"\n{FLAME}{BOLD}  🔥 DRAGONFIRE{RESET}  torching {o['target']} …\n")
        try:
            r = run_audit(o["target"], brand=o["brand"], service=o["service"],
                          towns=o["towns"].split(","), max_pages=o["max_pages"],
                          base_url=o["base_url"], ai=not o["no_ai"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        audit = save_audit(r)
        self.stdout.write(f"  {BOLD}{r['score']}/100  {FLAME}{r['heat'].upper()}{RESET}")
        self.stdout.write(f"  {DIM}{r['verdict']}{RESET}\n")
        for key, c in r["categories"].items():
            if c["score"] is None:
                continue
            bar = "█" * (c["score"] // 5) + DIM + "░" * (20 - c["score"] // 5) + RESET
            self.stdout.write(f"  {c['label']:<14} {FLAME}{bar} {c['score']:>3}")
        self.stdout.write(f"\n  {BOLD}Fix these first{RESET}")
        for i, f in enumerate(r["top_fixes"], 1):
            self.stdout.write(f"  {i}. {SEV[f['severity']]}  {f['title']}")

        out = Path(o["out"]) if o["out"] else (
            Path(settings.BASE_DIR) / "reports" / f"{slugify(r['domain'])}-{audit.created:%Y-%m-%d}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_to_string("audits/report.html", {
            "audit": audit, "r": r, "standalone": True,
            "agency": settings.DRAGONFIRE_AGENCY, "agency_url": settings.DRAGONFIRE_AGENCY_URL,
        }), encoding="utf-8")
        self.stdout.write(f"\n  Report → {out}\n  Web view → /report/{audit.pk}/\n")
