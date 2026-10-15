from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import (DOMAINS, WORK_MODES, Allocation, AllocationStatus, Application, AppStatus, Internship,
                        InternshipStatus, Role)
from app.services import match_service
from app.services.applications import ApplicationError, update_status
from app.services.audit import log_action
from app.services.forms import apply_internship, notify_internship_update, parse_internship_form
from app.utils.decorators import role_required
from app.utils.validators import clean_str

bp = Blueprint("company", __name__)


@bp.before_request
@role_required(Role.COMPANY)
def guard():
    if current_user.company_profile is None:
        abort(403)


def me():
    return current_user.company_profile


def own_internship(iid):
    i = db.get_or_404(Internship, iid)
    if i.company_id != me().id:
        abort(403)
    return i


@bp.route("/dashboard")
def dashboard():
    c = me()
    internships = c.internships
    ids = [i.id for i in internships] or [-1]
    apps = Application.query.filter(Application.internship_id.in_(ids)).all()
    counts = {s: 0 for s in AppStatus.ALL}
    for a in apps:
        counts[a.status] += 1
    allocated = Allocation.query.filter(Allocation.internship_id.in_(ids),
                                        Allocation.status == AllocationStatus.ACTIVE).count()
    recent = sorted(apps, key=lambda a: a.created_at, reverse=True)[:6]
    return render_template("company/dashboard.html", c=c, internships=internships, counts=counts,
                           total_apps=len(apps), allocated=allocated, recent=recent)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    c = me()
    if request.method == "POST":
        name = clean_str(request.form.get("company_name"), 150)
        if len(name) < 2:
            flash("Company name is required.", "danger")
            return render_template("company/profile.html", c=c), 400
        website = clean_str(request.form.get("website"), 255)
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        c.company_name = name
        c.industry = clean_str(request.form.get("industry"), 80) or None
        c.website = website or None
        c.location = clean_str(request.form.get("location"), 120) or None
        c.contact_person = clean_str(request.form.get("contact_person"), 120) or None
        c.description = clean_str(request.form.get("description"), 5000) or None
        db.session.commit()
        flash("Company profile saved.", "success")
        return redirect(url_for("company.profile"))
    return render_template("company/profile.html", c=c)


@bp.route("/internships")
def internships():
    c = me()
    items = sorted(c.internships, key=lambda i: i.created_at, reverse=True)
    status = request.args.get("status")
    if status in InternshipStatus.ALL:
        items = [i for i in items if i.status == status]
    return render_template("company/internships.html", items=items, c=c)


@bp.route("/internships/new", methods=["GET", "POST"])
def new_internship():
    c = me()
    if request.method == "POST":
        data, errors = parse_internship_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("internship_form.html", i=None, form=request.form, domains=DOMAINS,
                                   modes=WORK_MODES, companies=None, back=url_for("company.internships")), 400
        i = Internship(company_id=c.id, status=InternshipStatus.DRAFT)
        db.session.add(i)
        apply_internship(i, data)
        if request.form.get("publish") and c.is_verified:
            i.status = InternshipStatus.PUBLISHED
        db.session.commit()
        if request.form.get("publish") and not c.is_verified:
            flash("Saved as draft. Your company must be verified by the placement cell before publishing.", "warning")
        else:
            flash(f"Internship '{i.title}' saved as {i.status}.", "success")
        return redirect(url_for("company.internships"))
    return render_template("internship_form.html", i=None, form=None, domains=DOMAINS, modes=WORK_MODES,
                           companies=None, back=url_for("company.internships"))


@bp.route("/internships/<int:iid>/edit", methods=["GET", "POST"])
def edit_internship(iid):
    i = own_internship(iid)
    if request.method == "POST":
        data, errors = parse_internship_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("internship_form.html", i=i, form=request.form, domains=DOMAINS,
                                   modes=WORK_MODES, companies=None, back=url_for("company.internships")), 400
        apply_internship(i, data)
        notified = notify_internship_update(i)
        db.session.commit()
        flash("Internship updated." + (f" {notified} applicant(s) notified." if notified else ""), "success")
        return redirect(url_for("company.internships"))
    return render_template("internship_form.html", i=i, form=None, domains=DOMAINS, modes=WORK_MODES,
                           companies=None, back=url_for("company.internships"))


@bp.route("/internships/<int:iid>/status", methods=["POST"])
def set_internship_status(iid):
    i = own_internship(iid)
    status = request.form.get("status")
    if status not in InternshipStatus.ALL:
        abort(400)
    if status == InternshipStatus.PUBLISHED and not me().is_verified:
        flash("Your company must be verified before publishing internships.", "warning")
        return redirect(url_for("company.internships"))
    i.status = status
    log_action("internship.status", "internship", i.id, status)
    db.session.commit()
    flash(f"'{i.title}' is now {status}.", "success")
    return redirect(request.referrer or url_for("company.internships"))


@bp.route("/internships/<int:iid>/applicants")
def applicants(iid):
    i = own_internship(iid)
    rows = match_service.rank_applicants(i)
    db.session.commit()
    status = request.args.get("status")
    if status in AppStatus.ALL:
        rows = [r for r in rows if r[0].status == status]
    return render_template("applicants.html", i=i, rows=rows, base="company", statuses=AppStatus.ALL,
                           transitions=AppStatus.COMPANY_TRANSITIONS)


@bp.route("/applications/<int:aid>")
def application_detail(aid):
    a = db.get_or_404(Application, aid)
    if a.internship.company_id != me().id:
        abort(403)
    r = match_service.match_for(a.student, a.internship)
    db.session.commit()
    return render_template("application_detail.html", a=a, r=r, base="company",
                           transitions=AppStatus.COMPANY_TRANSITIONS)


@bp.route("/applications/<int:aid>/status", methods=["POST"])
def application_status(aid):
    a = db.get_or_404(Application, aid)
    try:
        update_status(a, request.form.get("status"), current_user, request.form.get("note", ""))
        flash(f"{a.student.user.name}: status changed to {a.status}.", "success")
    except ApplicationError as e:
        if e.status == 403:
            abort(403)
        flash(e.message, "danger")
    return redirect(request.referrer or url_for("company.applicants", iid=a.internship_id))


@bp.route("/allocations")
def allocations():
    ids = [i.id for i in me().internships] or [-1]
    allocs = (Allocation.query.filter(Allocation.internship_id.in_(ids),
                                      Allocation.status == AllocationStatus.ACTIVE)
              .order_by(Allocation.internship_id, Allocation.score.desc()).all())
    return render_template("company/allocations.html", allocs=allocs)
