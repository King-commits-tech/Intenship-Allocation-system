"""Small server-side validation helpers (forms are validated here, not only in the browser)."""
import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class FormErrors(list):
    def add(self, msg):
        self.append(msg)


def clean_str(value, max_len=255):
    value = (value or "").strip()
    return value[:max_len]


def valid_email(email):
    return bool(email) and len(email) <= 255 and bool(EMAIL_RE.match(email))


def password_problems(password):
    problems = []
    if len(password or "") < 8:
        problems.append("Password must be at least 8 characters long.")
    if password and (not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password)):
        problems.append("Password must contain letters and numbers.")
    return problems


def opt_float(value, name, errors, lo=None, hi=None):
    value = (value or "").strip() if isinstance(value, str) else value
    if value in ("", None):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        errors.add(f"{name} must be a number.")
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        errors.add(f"{name} must be between {lo:g} and {hi:g}.")
        return None
    return v


def opt_int(value, name, errors, lo=None, hi=None):
    value = (value or "").strip() if isinstance(value, str) else value
    if value in ("", None):
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        errors.add(f"{name} must be a whole number.")
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        errors.add(f"{name} must be between {lo} and {hi}.")
        return None
    return v


def opt_date(value, name, errors):
    value = (value or "").strip() if isinstance(value, str) else value
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        errors.add(f"{name} must be a date (YYYY-MM-DD).")
        return None


def safe_next(target):
    """Allow only local redirects."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None
