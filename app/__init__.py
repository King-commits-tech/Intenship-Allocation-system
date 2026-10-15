"""Flask application factory."""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError

from app.extensions import csrf, db, login_manager, migrate
from config import config_by_name


def create_app(config_name=None):
    config_name = config_name or os.environ.get("FLASK_CONFIG", "development")
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_by_name.get(config_name, config_by_name["development"]))

    if config_name == "production" and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("SECRET_KEY must be set in production.")

    _ensure_dirs(app)
    _configure_logging(app)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401  (register models)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    from app.routes.admin import bp as admin_bp
    from app.routes.api import bp as api_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.company import bp as company_bp
    from app.routes.main import bp as main_bp
    from app.routes.student import bp as student_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(company_bp, url_prefix="/company")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    from app.utils.template_helpers import register_template_helpers
    register_template_helpers(app)
    _register_error_handlers(app)

    from app.cli import register_cli
    register_cli(app)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    return app


def _ensure_dirs(app):
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(os.path.abspath(uri.replace("sqlite:///", ""))), exist_ok=True)


def _configure_logging(app):
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    app.logger.setLevel(level)
    if app.testing:
        return
    log_dir = os.path.join(os.path.dirname(app.root_path), "instance", "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(os.path.join(log_dir, "app.log"), maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(level)
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)


def _wants_json():
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _register_error_handlers(app):
    def render(code, title, message):
        if _wants_json():
            return jsonify({"error": message, "status": code}), code
        return render_template("errors/error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return render(400, "Bad request", getattr(e, "description", "The request was invalid."))

    @app.errorhandler(401)
    def unauthorized(e):
        return render(401, "Login required", "Please log in to continue.")

    @app.errorhandler(403)
    def forbidden(e):
        return render(403, "Access denied", "You do not have permission to access this page.")

    @app.errorhandler(404)
    def not_found(e):
        return render(404, "Not found", "The page or resource you requested does not exist.")

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render(405, "Method not allowed", "This action is not allowed here.")

    @app.errorhandler(413)
    def too_large(e):
        msg = f"File too large. Maximum resume size is {app.config['MAX_RESUME_MB']:g} MB."
        if _wants_json():
            return jsonify({"error": msg, "status": 413}), 413
        flash(msg, "danger")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if _wants_json():
            return jsonify({"error": "CSRF token missing or invalid. Reload the page and try again.",
                            "status": 400}), 400
        flash("Your session form expired. Please try again.", "warning")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        app.logger.exception("Unhandled server error")
        return render(500, "Something went wrong", "An unexpected error occurred. It has been logged.")
