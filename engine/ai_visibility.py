"""
Does AI recommend you?

Asks ChatGPT, Claude and Perplexity the questions your customers would ask,
then checks whether your name or website comes up.

Runs only for the providers you've added an API key for (see .env.example).
Honest caveat, shown in the report too: OpenAI/Anthropic API models answer from
what they learned in training unless web search is switched on, so they lag
behind. Perplexity searches the live web, so it's the closest to "right now".
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests

TIMEOUT = 60


def build_prompts(service: str, towns: list[str]) -> list[str]:
    service = service or "small business website designer"
    towns = towns or ["the UK"]
    prompts = []
    for town in towns[:3]:
        prompts.append(f"Who are the best {service}s in {town}? Give a short list with their websites.")
        prompts.append(f"I need a {service} in {town}. Who would you recommend and why?")
    return prompts


def _openai(prompt):
    key = os.environ.get("OPENAI_API_KEY")
    r = requests.post("https://api.openai.com/v1/chat/completions", timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(prompt):
    key = os.environ.get("ANTHROPIC_API_KEY")
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                      json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"),
                            "max_tokens": 800,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _perplexity(prompt):
    key = os.environ.get("PERPLEXITY_API_KEY")
    r = requests.post("https://api.perplexity.ai/chat/completions", timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.environ.get("PERPLEXITY_MODEL", "sonar"),
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    cites = data.get("citations") or [s.get("url") for s in data.get("search_results", []) if s.get("url")]
    return text + ("\n\nSources: " + " ".join(cites) if cites else "")


PROVIDERS = {
    "ChatGPT": ("OPENAI_API_KEY", _openai),
    "Claude": ("ANTHROPIC_API_KEY", _anthropic),
    "Perplexity": ("PERPLEXITY_API_KEY", _perplexity),
}


def available_providers() -> list[str]:
    return [name for name, (env, _) in PROVIDERS.items() if os.environ.get(env)]


DOMAIN_RX = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:co\.uk|org\.uk|com|uk|net|org|io|wales|co|design|studio))\b", re.I)


def run(brand: str, base_url: str, service: str, towns: list[str]) -> dict:
    providers = available_providers()
    if not providers:
        return {"ran": False, "providers": [], "results": []}
    domain = urlparse(base_url).netloc.lower().replace("www.", "")
    needles = [n.lower() for n in (brand, domain) if n]
    results = []
    competitors = {}
    for prompt in build_prompts(service, towns):
        row = {"prompt": prompt, "answers": {}}
        for name in providers:
            try:
                text = PROVIDERS[name][1](prompt)
            except Exception as exc:  # noqa: BLE001 — one bad provider shouldn't kill the report
                row["answers"][name] = {"error": str(exc)[:160]}
                continue
            low = text.lower()
            hit = any(n in low for n in needles)
            snippet = ""
            if hit:
                i = min(low.find(n) for n in needles if n in low)
                snippet = text[max(0, i - 120): i + 180].strip()
            for d in DOMAIN_RX.findall(text):
                d = d.lower().replace("www.", "")
                if d != domain and not d.endswith(("google.com", "wikipedia.org", "yell.com", "checkatrade.com")):
                    competitors[d] = competitors.get(d, 0) + 1
            row["answers"][name] = {"mentioned": hit, "snippet": snippet}
        results.append(row)
    total = sum(1 for r in results for a in r["answers"].values() if "mentioned" in a)
    hits = sum(1 for r in results for a in r["answers"].values() if a.get("mentioned"))
    return {"ran": True, "providers": providers, "results": results,
            "hits": hits, "total": total,
            "share": round(100 * hits / total) if total else 0,
            "competitors": sorted(competitors.items(), key=lambda x: -x[1])[:8]}
