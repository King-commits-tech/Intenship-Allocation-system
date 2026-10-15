"""Application configuration.

All secrets and database credentials come from environment variables
(optionally loaded from a local ``.env`` file). Nothing sensitive is hardcoded.
"""
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_database_uri():
    """Resolve the database URI.

    Priority:
    1. DATABASE_URL (full SQLAlchemy URI)
    2. DB_ENGINE=mysql + MYSQL_* variables
    3. SQLite file in ./instance (default, zero setup)
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    engine = os.environ.get("DB_ENGINE", "sqlite").lower()
    if engine == "mysql":
        user = os.environ.get("MYSQL_USER", "internship")
        password = quote_plus(os.environ.get("MYSQL_PASSWORD", ""))
        host = os.environ.get("MYSQL_HOST", "localhost")
        port = os.environ.get("MYSQL_PORT", "3306")
        name = os.environ.get("MYSQL_DATABASE", "internship_db")
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"
    sqlite_path = os.environ.get("SQLITE_PATH", os.path.join(BASE_DIR, "instance", "internship.db"))
    return "sqlite:///" + sqlite_path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_SECONDS", 60 * 60 * 8))

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    # Uploads
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "instance", "uploads"))
    MAX_RESUME_MB = float(os.environ.get("MAX_RESUME_MB", 2))
    MAX_CONTENT_LENGTH = int(float(os.environ.get("MAX_RESUME_MB", 2)) * 1024 * 1024) + 64 * 1024

    # Login throttling
    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 5))
    LOGIN_LOCK_MINUTES = int(os.environ.get("LOGIN_LOCK_MINUTES", 10))

    # Skill dictionary (configurable)
    SKILLS_FILE = os.environ.get("SKILLS_FILE", os.path.join(BASE_DIR, "app", "data", "skills.json"))

    # Pagination
    PAGE_SIZE = int(os.environ.get("PAGE_SIZE", 9))

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SECRET_KEY = "test-secret"
    LOGIN_MAX_ATTEMPTS = 3


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
