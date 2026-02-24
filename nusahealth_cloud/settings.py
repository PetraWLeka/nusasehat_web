"""
NusaHealth Cloud — Django Settings
Security-hardened configuration with environment variable support.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# =============================================================
# SECURITY — All secrets loaded from environment variables
# =============================================================
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-ME-IN-PRODUCTION"
)

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]


# =============================================================
# Application definition
# =============================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "axes",
    # Project apps
    "core.apps.CoreConfig",
    "patients.apps.PatientsConfig",
    "consultations.apps.ConsultationsConfig",
    "laboratory.apps.LaboratoryConfig",
    "reports.apps.ReportsConfig",
    "library.apps.LibraryConfig",
    "nutrition.apps.NutritionConfig",
    "education.apps.EducationConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SessionTimeoutMiddleware",
    "core.middleware.AuditLogMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.rate_limit.RateLimitMiddleware",
]

ROOT_URLCONF = "nusahealth_cloud.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.global_context",
            ],
        },
    },
]

WSGI_APPLICATION = "nusahealth_cloud.wsgi.application"


# =============================================================
# Database — SQLite default, PostgreSQL optional
# =============================================================

_db_engine = os.getenv("DATABASE_ENGINE", "django.db.backends.sqlite3")

if _db_engine == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": _db_engine,
            "NAME": os.getenv("DATABASE_NAME", "nusahealth_db"),
            "USER": os.getenv("DATABASE_USER", ""),
            "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
            "HOST": os.getenv("DATABASE_HOST", "localhost"),
            "PORT": os.getenv("DATABASE_PORT", "5432"),
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }


# =============================================================
# Authentication
# =============================================================

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/auth/login/"


# =============================================================
# django-axes — Brute-force login protection
# =============================================================

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True


# =============================================================
# Session Security — auto-logout after 30 min inactivity
# =============================================================

SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "1800"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = True

# Production-only cookie settings
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() in ("true", "1")
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
else:
    X_FRAME_OPTIONS = "SAMEORIGIN"


# =============================================================
# Internationalization
# =============================================================

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True


# =============================================================
# Static & Media files
# =============================================================

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "static_collected"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media_uploads"


# =============================================================
# Django REST Framework
# =============================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "60/minute",
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}


# =============================================================
# Celery — async task queue for AI inference
# =============================================================

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Jakarta"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 120  # 2 minute hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 90

# Windows: billiard prefork pool causes PermissionError [WinError 5].
# Use 'solo' (single-threaded) pool for local development on Windows.
# Production on Linux uses the default 'prefork' pool automatically.
import sys
if sys.platform == "win32":
    CELERY_WORKER_POOL = "solo"
    CELERY_WORKER_CONCURRENCY = 1


# =============================================================
# AI Backend — Switch between "cloud_run" and "openrouter"
# =============================================================

AI_BACKEND = os.getenv("AI_BACKEND", "cloud_run")  # "cloud_run" | "vertex_ai" | "openrouter"

# ── Google Cloud Run + vLLM (default — MedGemma) ─────────────
# Two Cloud Run services, each running vLLM with OpenAI-compatible API.
# 4B  = fast multimodal triage (L4 GPU)
# 27B = deep text-only specialist (L4 GPU, Unsloth 4-bit quantized)
CLOUD_RUN_4B_URL = os.getenv("CLOUD_RUN_4B_URL", "")
CLOUD_RUN_27B_URL = os.getenv("CLOUD_RUN_27B_URL", "")
CLOUD_RUN_MODEL_4B = os.getenv("CLOUD_RUN_MODEL_4B", "google/medgemma-4b-it")
CLOUD_RUN_MODEL_27B = os.getenv("CLOUD_RUN_MODEL_27B", "google/medgemma-27b-text-it")

# ── Google Cloud (shared) ────────────────────────────────────
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── Vertex AI (alternative — google-genai SDK) ─────────────────
VERTEX_AI_LOCATION = os.getenv("VERTEX_AI_LOCATION", "us-central1")
VERTEX_AI_MODEL_4B = os.getenv("VERTEX_AI_MODEL_4B", "medgemma-4b-it")
VERTEX_AI_MODEL_27B = os.getenv("VERTEX_AI_MODEL_27B", "medgemma-27b-text-it")

# ── OpenRouter (alternative — free tier, uses Gemma not MedGemma) ──
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://nusahealth.id")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "NusaHealth Cloud")

# ── AI Enabled — True if the active backend is configured ────
_vertex_ai_ok = bool(GCP_PROJECT_ID)
_cloud_run_ok = bool(CLOUD_RUN_4B_URL) and CLOUD_RUN_4B_URL.startswith("https://")
_openrouter_ok = bool(OPENROUTER_API_KEY)
if AI_BACKEND == "vertex_ai":
    AI_ENABLED = _vertex_ai_ok
elif AI_BACKEND == "cloud_run":
    AI_ENABLED = _cloud_run_ok
else:
    AI_ENABLED = _openrouter_ok

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "nusahealth-medical-images")


# =============================================================
# ChromaDB — RAG vector database
# =============================================================

CHROMA_PERSIST_DIRECTORY = os.getenv("CHROMA_PERSIST_DIRECTORY", str(BASE_DIR / "chroma_db"))
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "nusahealth_documents")


# =============================================================
# Logging — with PII masking support
# =============================================================

ENABLE_PII_MASKING = os.getenv("ENABLE_PII_MASKING", "True").lower() in ("true", "1")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {module} {message}",
            "style": "{",
        },
    },
    "filters": {
        "pii_filter": {
            "()": "core.logging_filters.PIIMaskingFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["pii_filter"],
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "nusahealth.log",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
            "filters": ["pii_filter"],
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
        "nusahealth": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "celery.utils.functional": {"handlers": [], "level": "CRITICAL", "propagate": False},
        "urllib3": {"handlers": [], "level": "WARNING", "propagate": False},
    },
}


# =============================================================
# File Upload Limits — security
# =============================================================

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024


# =============================================================
# Default primary key field type
# =============================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================
# Cache backend (used by rate limiter; upgrade to Redis in prod)
# =============================================================

CACHES = {
    "default": {
        "BACKEND": os.getenv(
            "CACHE_BACKEND",
            "django.core.cache.backends.locmem.LocMemCache",
        ),
        "LOCATION": os.getenv("CACHE_LOCATION", "nusahealth-ratelimit"),
        "TIMEOUT": 300,
    }
}


# =============================================================
# Rate Limiting (protects VPS + Vertex AI quota)
# =============================================================

RATE_LIMIT_PAGE_REQUESTS = int(os.getenv("RATE_LIMIT_PAGE_REQUESTS", "120"))   # /min/IP
RATE_LIMIT_API_REQUESTS = int(os.getenv("RATE_LIMIT_API_REQUESTS", "40"))      # /min/user
RATE_LIMIT_AI_REQUESTS = int(os.getenv("RATE_LIMIT_AI_REQUESTS", "10"))        # /min/user
RATE_LIMIT_AI_DAILY = int(os.getenv("RATE_LIMIT_AI_DAILY", "200"))             # /day/user
RATE_LIMIT_LOGIN_ATTEMPTS = int(os.getenv("RATE_LIMIT_LOGIN_ATTEMPTS", "10"))  # /min/IP


# =============================================================
# Content Security Policy headers (for additional security)
# =============================================================

CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "unpkg.com", "cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "cdn.tailwindcss.com", "fonts.googleapis.com")
CSP_FONT_SRC = ("'self'", "fonts.gstatic.com")
CSP_IMG_SRC = ("'self'", "data:", "blob:")
