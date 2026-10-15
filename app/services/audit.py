from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def log_action(action, entity_type=None, entity_id=None, details=None, user=None):
    """Add an audit entry to the current session (committed with the caller's transaction)."""
    uid = None
    if user is not None:
        uid = user.id
    elif has_request_context() and current_user and current_user.is_authenticated:
        uid = current_user.id
    ip = request.remote_addr if has_request_context() else None
    db.session.add(AuditLog(user_id=uid, action=action, entity_type=entity_type, entity_id=entity_id,
                            details=(details or "")[:2000], ip_address=ip))
