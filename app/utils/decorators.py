from functools import wraps

from flask import abort, jsonify, request
from flask_login import current_user


def role_required(*roles):
    """Server-side role check. Returns JSON errors for /api routes, HTML errors otherwise."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            is_api = request.path.startswith("/api/")
            if not current_user.is_authenticated:
                if is_api:
                    return jsonify({"error": "Authentication required.", "status": 401}), 401
                from app.extensions import login_manager
                return login_manager.unauthorized()
            if current_user.role not in roles:
                if is_api:
                    return jsonify({"error": "You do not have permission for this action.", "status": 403}), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
