from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import CompanyProfile, Role, StudentProfile, User
from app.services.audit import log_action
from app.services.notifications import notify
from app.utils.validators import FormErrors, clean_str, password_problems, safe_next, valid_email

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = clean_str(request.form.get("email")).lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        generic = "Invalid email or password."
        if user is None:
            flash(generic, "danger")
            return render_template("auth/login.html", email=email), 401
        if user.is_locked():
            flash("Too many failed attempts. This account is temporarily locked; try again later.", "danger")
            return render_template("auth/login.html", email=email), 429
        if not user.check_password(password):
            user.register_failed_login(current_app.config["LOGIN_MAX_ATTEMPTS"],
                                       current_app.config["LOGIN_LOCK_MINUTES"])
            db.session.commit()
            flash(generic, "danger")
            return render_template("auth/login.html", email=email), 401
        if not user.is_active:
            flash("This account has been deactivated. Contact the placement cell.", "danger")
            return render_template("auth/login.html", email=email), 403
        user.register_successful_login()
        db.session.commit()
        session.clear()  # prevent session fixation
        login_user(user, remember=bool(request.form.get("remember")))
        session.permanent = True
        flash(f"Welcome back, {user.name}!", "success")
        return redirect(safe_next(request.args.get("next")) or url_for("main.dashboard"))
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    role = request.values.get("role", Role.STUDENT)
    if role not in (Role.STUDENT, Role.COMPANY):
        role = Role.STUDENT
    form = {}
    if request.method == "POST":
        errors = FormErrors()
        form = {k: clean_str(request.form.get(k)) for k in ("name", "email", "company_name", "industry",
                                                             "department")}
        form["email"] = form["email"].lower()
        password = request.form.get("password") or ""
        if len(form["name"]) < 2:
            errors.add("Please enter your full name.")
        if not valid_email(form["email"]):
            errors.add("Please enter a valid email address.")
        elif User.query.filter_by(email=form["email"]).first():
            errors.add("An account with this email already exists.")
        errors.extend(password_problems(password))
        if password != request.form.get("confirm_password"):
            errors.add("Passwords do not match.")
        if role == Role.COMPANY and len(form["company_name"]) < 2:
            errors.add("Company name is required.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", role=role, form=form), 400

        user = User(email=form["email"], name=form["name"], role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if role == Role.STUDENT:
            db.session.add(StudentProfile(user_id=user.id, department=form["department"] or None))
        else:
            db.session.add(CompanyProfile(user_id=user.id, company_name=form["company_name"],
                                          industry=form["industry"] or None, contact_person=form["name"]))
            for admin in User.query.filter_by(role=Role.ADMIN).all():
                notify(admin, "New company registration",
                       f"{form['company_name']} registered and is awaiting verification.", "info",
                       "/admin/companies")
        log_action("user.register", "user", user.id, f"role={role}", user=user)
        db.session.commit()
        flash("Account created. Please log in." + (
            " Your company must be verified by the placement cell before internships can be published."
            if role == Role.COMPANY else ""), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", role=role, form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
