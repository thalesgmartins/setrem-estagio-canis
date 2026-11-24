"""Centralized application settings loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'laika.db'}",
)

SECRET_KEY = os.getenv("SECRET_KEY", "laika-dev-secret-key-change-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/uploads/laika"))

# Google OAuth 2.0 (OpenID Connect)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/auth/google/callback",
)

# Comma-separated emails automatically granted admin role on first login
_raw_admins = os.getenv("ADMIN_EMAILS", "coordenacao@patasepelos.org.br")
ADMIN_EMAILS: frozenset[str] = frozenset(
    email.strip().lower() for email in _raw_admins.split(",") if email.strip()
)

# Public NGO contact settings (used on the public adoption catalog)
ONG_WHATSAPP = os.getenv("ONG_WHATSAPP", "5555996112233")
ONG_CITY = os.getenv("ONG_CITY", "Horizontina/RS")

# Populate demo mock data on empty database (disabled by default for clean DB)
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}


def google_oauth_configured() -> bool:
    """Return True when Google OAuth credentials are configured in the environment.

    Returns:
        Boolean indicating whether Google OAuth 2.0 login is enabled.
    """
    return bool(GOOGLE_CLIENT_ID.strip() and GOOGLE_CLIENT_SECRET.strip())
