"""Settings for Dragonfire SEO. Secrets live in .env (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "audits",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dragonfire_seo.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "audits.views.brand_context",
    ]},
}]

WSGI_APPLICATION = "dragonfire_seo.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3")}}

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Dragonfire
DRAGONFIRE_AGENCY = os.environ.get("DRAGONFIRE_AGENCY", "Sarah J Hill")
DRAGONFIRE_AGENCY_URL = os.environ.get("DRAGONFIRE_AGENCY_URL", "https://sarahjhill.com")
DRAGONFIRE_ALLOW_FOLDERS = os.environ.get("DRAGONFIRE_ALLOW_FOLDERS", "1" if DEBUG else "0") == "1"

# --- Public free check (lead magnet) -------------------------------------
# DRAGONFIRE_PUBLIC=1 once deployed: only /free-check/ is open; everything else needs your admin login.
DRAGONFIRE_PUBLIC = os.environ.get("DRAGONFIRE_PUBLIC", "0") == "1"
DRAGONFIRE_PUBLIC_MAX_PAGES = int(os.environ.get("DRAGONFIRE_PUBLIC_MAX_PAGES", "12"))  # keeps it under Heroku's 30s limit
DRAGONFIRE_PUBLIC_AI = os.environ.get("DRAGONFIRE_PUBLIC_AI", "0") == "1"               # AI checks cost money; off by default
DRAGONFIRE_FREE_CHECKS_PER_HOUR = int(os.environ.get("DRAGONFIRE_FREE_CHECKS_PER_HOUR", "5"))
DRAGONFIRE_LEAD_ALERT_TO = os.environ.get("DRAGONFIRE_LEAD_ALERT_TO", "")             # e.g. sarah@sarahjhill.com
DRAGONFIRE_BOOKING_URL = os.environ.get("DRAGONFIRE_BOOKING_URL", "https://sarahjhill.com/project-os/forms/intake.html")
LOGIN_URL = "admin:login"

# Email (for lead alerts). Without these, emails print to the terminal instead.
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- Deployment (Heroku) ---------------------------------------------------
if os.environ.get("DATABASE_URL"):
    import dj_database_url
    DATABASES["default"] = dj_database_url.config(conn_max_age=600, ssl_require=True)
if not DEBUG:
    STATIC_ROOT = BASE_DIR / "staticfiles"
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
