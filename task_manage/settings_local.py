from .settings import *  # noqa: F403,F401


DEBUG = True
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "client-tickets-local-secret")  # noqa: F405
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",  # noqa: F405
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CLIENT_TICKETS_BASE_URL = os.environ.get("CLIENT_TICKETS_BASE_URL", "http://127.0.0.1:5467")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
