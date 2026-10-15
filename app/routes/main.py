import os

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import (Application, CompanyProfile, Internship, InternshipStatus, Notification, Role,
                        StudentProfile)
from app.services.resume import ResumeError, resolve_path

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    stats = {
        "internships": Internship.query.filter_by(status=InternshipStatus.PUBLISHED).count(),
        "companies": CompanyProfile.query.filter_by(is_verified=True).count(),
        "students": StudentProfile.query.count(),
        "applications": Application.query.count(),
    }
    latest = (Internship.query.filter_by(status=InternshipStatus.PUBLISHED)
              .order_by(Internship.created_at.desc()).limit(3).all())
    return render_template("index.html", stats=stats, latest=latest)


@bp.route("/dashboard")
@login_required
def dashboard():
    target = {Role.STUDENT: "student.dashboard", Role.COMPANY: "company.dashboard",
              Role.ADMIN: "admin.dashboard"}.get(current_user.role)
    if not target:
        abort(403)
    return redirect(url_for(target))


@bp.route("/notifications")
@login_required
def notifications():
    page = request.args.get("page", 1, type=int)
    q = current_user.notifications.order_by(Notification.created_at.desc())
    if request.args.get("filter") == "unread":
        q = q.filter_by(is_read=False)
    pagination = (q).paginate(page=page, per_page=15, error_out=False)
    return render_template("notifications.html", pagination=pagination)


@bp.route("/notifications/<int:nid>/read", methods=["POST"])
@login_required
def mark_read(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first_or_404()
    n.is_read = True
    db.session.commit()
    if n.link and request.form.get("open"):
        return redirect(n.link)
    return redirect(request.referrer or url_for("main.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    current_user.notifications.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(request.referrer or url_for("main.notifications"))


def can_view_resume(user, profile):
    """Owner, admins, and companies the student applied to may view a resume."""
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.STUDENT:
        return user.student_profile is not None and user.student_profile.id == profile.id
    if user.role == Role.COMPANY and user.company_profile:
        return (Application.query.join(Internship)
                .filter(Application.student_id == profile.id,
                        Internship.company_id == user.company_profile.id).first() is not None)
    return False


@bp.route("/resume/<int:student_id>")
@login_required
def resume(student_id):
    profile = db.session.get(StudentProfile, student_id)
    if profile is None or profile.resume is None:
        abort(404)
    if not can_view_resume(current_user, profile):
        abort(403)
    try:
        path = resolve_path(profile.resume.stored_filename)
    except ResumeError:
        abort(404)
    if not os.path.exists(path):
        abort(404)
    download_name = f"{profile.user.name.replace(' ', '_')}_resume.pdf"
    return send_file(path, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                     download_name=download_name, max_age=0)
