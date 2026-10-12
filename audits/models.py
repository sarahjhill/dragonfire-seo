import uuid

from django.db import models


class Audit(models.Model):
    """One torch of one website. The full report is stored as JSON in `results`."""

    target = models.CharField(max_length=500, help_text="URL or folder that was audited")
    domain = models.CharField(max_length=255, blank=True)
    brand = models.CharField(max_length=200, blank=True)
    service = models.CharField(max_length=200, blank=True)
    towns = models.CharField(max_length=300, blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    heat = models.CharField(max_length=40, blank=True)
    results = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.domain or self.target} — {self.score} ({self.created:%d %b %Y})"


class Lead(models.Model):
    """Someone who ran the public free check. Your sales pipeline."""

    STATUS = [("new", "New"), ("contacted", "Contacted"), ("call", "Call booked"),
              ("won", "Won"), ("lost", "Not now")]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    business = models.CharField(max_length=200, blank=True)
    service = models.CharField("What they do", max_length=200, blank=True)
    town = models.CharField(max_length=120, blank=True)
    website = models.CharField(max_length=500)
    consent = models.BooleanField(default=False, help_text="Agreed to be contacted about their report")
    newsletter_optin = models.BooleanField("Said yes to tips emails", default=False,
                                           help_text="Ticked the separate box. Only these people may get newsletters.")
    newsletter_optin_at = models.DateTimeField("Tips opt-in date", null=True, blank=True)
    audit = models.ForeignKey(Audit, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")
    status = models.CharField(max_length=20, choices=STATUS, default="new")
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.name} — {self.business or self.website}"

    @property
    def score(self):
        return self.audit.score if self.audit else None
