"""Runtime configuration.

Playbook rule "Dynamic Credentials": no secret is hard-coded here. Everything
sensitive (admin password, SMTP password, WhatsApp token) is injected at runtime
from environment variables / the local .env file, which is never committed.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _bootstrap_env_file():
    """Create a .env with random secrets on first run so nothing is hard-coded."""
    if ENV_FILE.exists():
        return
    template = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    template = template.replace("SECRET_KEY=", f"SECRET_KEY={secrets.token_hex(32)}", 1)
    template = template.replace("ADMIN_PASSWORD=", f"ADMIN_PASSWORD={secrets.token_urlsafe(10)}", 1)
    ENV_FILE.write_text(template, encoding="utf-8")


_bootstrap_env_file()
load_dotenv(ENV_FILE)


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # Organisation branding - change these in .env to use your own name
    ORG_NAME = os.getenv("ORG_NAME", "Northbridge Professional Association")
    ORG_SHORT = os.getenv("ORG_SHORT", "Northbridge (Metro Chapter)")

    # SQLite database (created on first run from db/schema.sql + db/seed.sql)
    DB_PATH = BASE_DIR / "data" / "memberdesk.db"
    SCHEMA_SQL = BASE_DIR / "db" / "schema.sql"
    SEED_SQL = BASE_DIR / "db" / "seed.sql"
    BACKUP_DIR = BASE_DIR / "data" / "backups"
    BACKUP_KEEP = _int("BACKUP_KEEP", 50)

    # Uploads (Aadhaar)
    UPLOAD_DIR = BASE_DIR / "uploads" / "aadhaar"
    ALLOWED_UPLOADS = {"pdf", "jpg", "jpeg", "png"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    SUBSCRIPTION_FEE = _int("SUBSCRIPTION_FEE", 2000)

    # Messaging (credentials injected at runtime only)
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
    DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "91")

    # Playbook rule "Per-Run Budgets": hard caps on outbound sends
    MAX_SEND_PER_BATCH = _int("MAX_SEND_PER_BATCH", 25)
    MAX_SEND_PER_DAY = _int("MAX_SEND_PER_DAY", 200)
