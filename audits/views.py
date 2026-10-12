import logging
import os

from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils.text import slugify

from engine import ai_visibility
from engine.runner import run_audit
from engine.sources import UnsafeTarget

from .forms import FreeCheckForm, TorchForm
from .models import Audit, Lead

log = logging.getLogger(__name__)


def private(view):
    """Your own pages (torch, history, reports). Open on your laptop; staff-only once deployed."""
    return staff_member_required(view) if settings.DRAGONFIRE_PUBLIC else view


def brand_context(request):
    """Makes the agency name available in every template."""
    return {"agency": settings.DRAGONFIRE_AGENCY, "agency_url": settings.DRAGONFIRE_AGENCY_URL,
            "booking_url": settings.DRAGONFIRE_BOOKING_URL, "public_mode": settings.DRAGONFIRE_PUBLIC}


def save_audit(results: dict) -> Audit:
    return Audit.objects.create(
        target=results["target"], domain=results["domain"], brand=results["brand"],
        service=results["service"], towns=", ".join(results["towns"]),
        score=results["score"], heat=results["heat"], results=results,
    )


@private
def home(request):
    form = TorchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        target = d["target"].strip()
        if os.path.isdir(os.path.expanduser(target)) and not settings.DRAGONFIRE_ALLOW_FOLDERS:
            messages.error(request, "Folder audits are switched off on this server.")
        else:
            try:
                results = run_audit(
                    target, brand=d["brand"], service=d["service"],
                    towns=[t for t in d["towns"].split(",")], max_pages=d["max_pages"], ai=d["ai"],
                )
            except (UnsafeTarget, ConnectionError, FileNotFoundError, ValueError) as exc:
                messages.error(request, str(exc))
            else:
                return redirect("audits:report", pk=save_audit(results).pk)
    return render(request, "audits/home.html", {
        "form": form,
        "recent": Audit.objects.all()[:5],
        "ai_ready": ai_visibility.available_providers(),
    })


@private
def history(request):
    return render(request, "audits/history.html", {"audits": Audit.objects.all()})


@private
def report(request, pk):
    audit = get_object_or_404(Audit, pk=pk)
    return render(request, "audits/report.html", {"audit": audit, "r": audit.results, "standalone": False})


@private
def download(request, pk):
    """The same report as a single self-contained HTML file you can email to a client."""
    audit = get_object_or_404(Audit, pk=pk)
    html = render_to_string("audits/report.html",
                            {"audit": audit, "r": audit.results, "standalone": True}, request=request)
    name = f"dragonfire-{slugify(audit.domain or 'report')}-{audit.created:%Y-%m-%d}.html"
    response = HttpResponse(html, content_type="text/html")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# --------------------------------------------------------------------------- #
# The public free check — your lead magnet
# --------------------------------------------------------------------------- #
def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")


def _rate_limited(request) -> bool:
    key = f"freecheck:{_client_ip(request)}"
    count = cache.get(key, 0)
    if count >= settings.DRAGONFIRE_FREE_CHECKS_PER_HOUR:
        return True
    cache.set(key, count + 1, 3600)
    return False


def _tell_sarah(request, lead):
    if not settings.DRAGONFIRE_LEAD_ALERT_TO:
        return
    url = request.build_absolute_uri(reverse("admin:audits_lead_change", args=[lead.pk]))
    body = (f"New free check!\n\n{lead.name} — {lead.business or '(no business name)'}\n"
            f"{lead.email}\n{lead.website}\nWhat they do: {lead.service or '—'}\nWhere: {lead.town or '—'}\n"
            f"Score: {lead.score}/100\n\nOpen in Dragonfire: {url}\n")
    try:
        send_mail(f"🔥 New lead: {lead.business or lead.name} scored {lead.score}",
                  body, None, [settings.DRAGONFIRE_LEAD_ALERT_TO])
    except Exception:  # noqa: BLE001 — a failed email must never lose the lead
        log.exception("Couldn't send lead alert")


def free_check(request):
    form = FreeCheckForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["company_url"]:                       # honeypot tripped: pretend all is well
            return redirect("audits:free_check")
        if _rate_limited(request):
            messages.error(request, "That's a lot of checks in one hour. Give it a little while and try again.")
        elif os.path.isdir(os.path.expanduser(d["website"])):
            messages.error(request, "That doesn't look like a website address.")
        else:
            try:
                results = run_audit(d["website"].strip(), brand=d["business"], service=d["service"],
                                    towns=[d["town"]] if d["town"] else [],
                                    max_pages=settings.DRAGONFIRE_PUBLIC_MAX_PAGES,
                                    ai=settings.DRAGONFIRE_PUBLIC_AI)
            except (UnsafeTarget, ConnectionError, ValueError) as exc:
                messages.error(request, f"We couldn't check that one: {exc}")
            else:
                audit = save_audit(results)
                lead = Lead.objects.create(name=d["name"], email=d["email"], business=d["business"],
                                           service=d["service"], town=d["town"], website=d["website"],
                                           consent=d["consent"], audit=audit,
                                           newsletter_optin=d["tips"],
                                           newsletter_optin_at=timezone.now() if d["tips"] else None)
                _tell_sarah(request, lead)
                return redirect("audits:free_result", token=lead.token)
    return render(request, "audits/free_check.html", {"form": form, "public_page": True})


def free_result(request, token):
    lead = get_object_or_404(Lead, token=token)
    r = lead.audit.results if lead.audit else None
    return render(request, "audits/free_result.html", {"lead": lead, "r": r, "public_page": True})
