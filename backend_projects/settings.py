import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-0-sntg)ni=u26o+9=)dafe87265r&t49(uwose90eh52cr!z1%"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "0") == "1"

ALLOWED_HOSTS = ["*"]

ASGI_APPLICATION = "backend_projects.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                (
                    os.environ.get("REDIS_HOST", "redis"),
                    int(os.environ.get("REDIS_PORT", "6379")),
                )
            ],
            "symmetric_encryption_keys": [SECRET_KEY],
        },
    },
}

# Application definition
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django.contrib.gis",
    "django.contrib.postgres",
    "channels",
    "rest_framework",
    "rest_framework.authtoken",
    "shared.apps.SharedConfig",
    "auth_app.apps.AuthAppConfig",
    "blogs_app.apps.BlogsAppConfig",
    "dead_stock_app.apps.DeadStockAppConfig",
    "expense_tracker_app.apps.ExpenseTrackerAppConfig",
    "todo_app.apps.TodoAppConfig",
    "weather_app.apps.WeatherAppConfig",
    "note_markdown_app.apps.NoteMarkdownAppConfig",
    "url_shortner_app.apps.UrlShortnerAppConfig",
    "device_classifier.apps.DeviceClassifierConfig",
    # "chat_app.apps.ChatAppConfig",
    "ecommerce_app.apps.EcommerceAppConfig",
    "web_gis_app.apps.WebGisAppConfig",
    "agent_manager.apps.AgentManagerConfig",
    "level_up_app.apps.LevelUpAppConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    # "shared.middleware.LoggingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# if DEBUG:
#     INSTALLED_APPS += ["debug_toolbar"]
#     MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

# CORS Configuration
# In production, set CORS_ALLOWED_ORIGINS env var as a comma-separated list,
# e.g. "https://worldofapps.bar,https://app.worldofapps.bar"
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [
        "http://localhost:3000",   # React dev
        "http://127.0.0.1:3000",
        "http://localhost:5173",   # Vite dev
        "http://127.0.0.1:5173",
        "https://worldofapps.bar",
        "https://app.worldofapps.bar",
        "https://api.worldofapps.bar",
    ]
)

CORS_ALLOW_ALL_ORIGINS = DEBUG   # True only in local dev (DEBUG=1)
CORS_ALLOW_CREDENTIALS = True

# Security/Proxy settings for K8s (behind Nginx/Cloudflare)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

CSRF_TRUSTED_ORIGINS = [
    "https://worldofapps.bar",
    "https://app.worldofapps.bar",
    "https://api.worldofapps.bar",
]

CORS_ALLOWED_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

ROOT_URLCONF = "backend_projects.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "debug": DEBUG,
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend_projects.wsgi.application"
ASGI_APPLICATION = "backend_projects.asgi.application"


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",  # Use PostGIS backend
        "NAME": os.environ.get("DB_NAME", "backend_projects"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": (
            f"redis://{os.environ.get('REDIS_HOST', 'redis')}"
            f":{os.environ.get('REDIS_PORT', '6379')}/0"
        ),
        "KEY_PREFIX": "backend_projects",
        "TIMEOUT": 300,
    },
}

# Celery Configuration
CELERY_BROKER_URL = (
    f"redis://{os.environ.get('REDIS_HOST', 'redis')}"
    f":{os.environ.get('REDIS_PORT', '6379')}/1"
)
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "cleanup-stale-pending-messages": {
        "task": "agent_manager.tasks.cleanup_stale_pending_messages",
        "schedule": 300,  # Every 5 minutes.
    },
    "dead-stock-sweep-stale": {
        "task": "dead_stock_app.tasks.sweep_stale_items",
        "schedule": 3600,  # Hourly.
    },
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "backend_projects.renderer.CustomJSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "dead_stock_app.authentication.JWTBearerAuthentication",
        "rest_framework.authentication.TokenAuthentication",  # Add standard token auth
        "auth_app.authentication.BearerAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "ds_search_anon": "60/min",
        "ds_search_auth": "300/min",
        "ds_lead_anon": "5/min",
        "ds_lead_auth": "20/min",
        "ds_otp_request": "1/min",
    },
}

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static"

# Additional static files directories (if any)
STATICFILES_DIRS = [
    BASE_DIR / "docs",
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INTERNAL_IPS = [
    "127.0.0.1",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# LLM Server Configuration
LLM_SERVER_CONFIG = {
    "BASE_URL": os.environ.get("LLM_SERVER_URL", "http://100.64.122.97:8080/v1"),
    "DEFAULT_MODEL": os.environ.get("LLM_DEFAULT_MODEL", "Qwen/Qwen3-8B-AWQ"),
    "TIMEOUT": int(
        os.environ.get("LLM_TIMEOUT", "120")
    ),  # Increased for geospatial tool processing
    "MAX_TOKENS": int(os.environ.get("LLM_MAX_TOKENS", "2000")),
    "TEMPERATURE": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
    "ENABLE_TOOLS": os.environ.get("LLM_ENABLE_TOOLS", "true").lower() == "true",
}


DEFAULT_CURRENCY = "INR"

# Dead Stock — OTP / JWT.
MSG91_AUTH_KEY = os.environ.get("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.environ.get("MSG91_TEMPLATE_ID", "")
MSG91_SENDER_ID = os.environ.get("MSG91_SENDER_ID", "DSTOCK")
DS_JWT_SECRET = os.environ.get("DS_JWT_SECRET", SECRET_KEY)
DS_JWT_TTL_SECONDS = int(os.environ.get("DS_JWT_TTL_SECONDS", "2592000"))
