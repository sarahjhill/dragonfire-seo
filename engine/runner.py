"""
The whole torch, start to finish: fetch → extract → check → score → extras.
Returns one plain dict that's easy to save as JSON and render as a report.
"""
from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

from . import ai_visibility
from .checks import CATEGORIES, Ctx, Finding, run_checks, short
from .page import extract
from .sources import make_source

SEV_SCORE = {"pass": 1.0, "warn": 0.5, "fail": 0.0}

HEAT = [  # (min score, name, verdict)
    (90, "Inferno", "Google takes you seriously. So do the robots. Keep feeding the fire."),
    (75, "Blaze", "Strong fire, a few damp logs. Fix the red ones and you're hard to beat."),
    (50, "Smoulder", "There's heat, but people are walking past. The fixes below are the bellows."),
    (0, "Damp squib", "Right now, search engines decide about you before you say a word. Let's change that."),
]


def heat_for(score: int):
    for minimum, name, verdict in HEAT:
        if score >= minimum:
            return name, verdict
    return HEAT[-1][1:]


def score_findings(findings: list[Finding], ai: dict | None):
    cats = {}
    for key, meta in CATEGORIES.items():
        scored = [f for f in findings if f.category == key and f.severity in SEV_SCORE and f.weight]
        total = sum(f.weight for f in scored)
        got = sum(f.weight * SEV_SCORE[f.severity] for f in scored)
        cats[key] = {**meta, "score": round(100 * got / total) if total else None,
                     "fails": sum(f.severity == "fail" for f in scored),
                     "warns": sum(f.severity == "warn" for f in scored),
                     "passes": sum(f.severity == "pass" for f in scored)}
    if ai and ai.get("ran"):
        cats["visibility"] = {"label": "AI visibility", "weight": 20,
                              "blurb": "When people ask AI, does your name come up?",
                              "score": ai["share"], "fails": 0, "warns": 0, "passes": 0}
    weighted = [(c["score"], c["weight"]) for c in cats.values() if c["score"] is not None]
    overall = round(sum(s * w for s, w in weighted) / sum(w for _, w in weighted)) if weighted else 0
    return overall, cats


def draft_llms_txt(brand, base_url, facts, home) -> str:
    lines = [f"# {brand or urlparse(base_url).netloc}", ""]
    if home and home.description:
        lines += [f"> {home.description}", ""]
    lines += ["## Key pages", ""]
    for f in facts:
        if f.noindex:
            continue
        label = (f.title or short(f.url)).split("|")[0].strip()
        desc = (f.description or "").strip()
        lines.append(f"- [{label}]({f.url})" + (f": {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def topic_ideas(service: str, towns: list[str]) -> list[str]:
    s = service or "your service"
    town = towns[0] if towns else "your area"
    return [
        f"How much does a {s} cost in {town}? (Real prices, not 'it depends')",
        f"What should you ask before hiring a {s}?",
        f"{s.capitalize()} vs doing it yourself: an honest comparison",
        f"How long does it take to work with a {s}? A week-by-week walkthrough",
        f"Red flags when choosing a {s} — and what good looks like",
        f"Case study: a real {town} project, start to finish, with numbers",
    ]


def run_audit(target: str, *, brand: str = "", service: str = "", towns: list[str] | None = None,
              max_pages: int = 40, base_url: str | None = None, ai: bool = True) -> dict:
    towns = [t.strip() for t in (towns or []) if t.strip()]
    snap = make_source(target, max_pages=max_pages, base_url=base_url).snapshot()
    if not snap.pages:
        raise ValueError("Found no HTML pages to check.")
    facts = [extract(p, snap.base_url) for p in snap.pages]
    ctx = Ctx(snap, facts, towns, brand, service)
    findings = run_checks(ctx)

    ai_result = ai_visibility.run(brand, snap.base_url, service, towns) if ai else {"ran": False, "providers": []}
    overall, cats = score_findings(findings, ai_result)
    heat, verdict = heat_for(overall)

    order = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    findings.sort(key=lambda f: (order[f.severity], -f.weight))
    priority = [f for f in findings if f.severity in ("fail", "warn")]
    priority.sort(key=lambda f: (-(f.weight * (2 if f.severity == "fail" else 1))))
    if any(f.id == "location-pages" and f.severity != "pass" for f in priority):
        # "no Birmingham page" already covers "Birmingham not in a title" — don't say it twice
        priority = [f for f in priority if not (f.id.startswith("town-") and f.severity == "warn")]

    return {
        "version": 1,
        "target": target,
        "mode": snap.mode,
        "base_url": snap.base_url,
        "domain": urlparse(snap.base_url).netloc,
        "brand": brand,
        "service": service,
        "towns": towns,
        "ran_at": dt.datetime.now().isoformat(timespec="minutes"),
        "score": overall,
        "heat": heat,
        "verdict": verdict,
        "categories": cats,
        "findings": [f.as_dict() for f in findings],
        "top_fixes": [f.as_dict() for f in priority[:5]],
        "counts": {s: sum(f.severity == s for f in findings) for s in ("fail", "warn", "pass")},
        "pages": [{"url": short(f.url), "title": f.title or "—", "words": f.word_count,
                   "h1": f.h1s[0] if f.h1s else "—", "noindex": f.noindex,
                   "schema": ", ".join(sorted(f.schema_types)) or "—"} for f in facts],
        "ai": ai_result,
        "ai_providers_missing": [p for p in ai_visibility.PROVIDERS if p not in ai_result.get("providers", [])],
        "llms_txt": draft_llms_txt(brand, snap.base_url, facts, ctx.home) if not snap.llms_txt else "",
        "topics": topic_ideas(service, towns),
        "notes": snap.notes,
    }
