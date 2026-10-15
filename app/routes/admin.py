import csv
import io

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import (DOMAINS, WORK_MODES, Allocation, AllocationRun, AllocationStatus, Announcement,
                        Application, AppStatus, AuditLog, CompanyProfile, Feedback, Internship,
                        InternshipStatus, Role, RunStatus, StudentProfile, User)
from app.services import allocation as alloc_service
from app.services import match_service
from app.services.applications import ApplicationError, update_status
from app.services.audit import log_action
from app.services.forms import apply_internship, notify_internship_update, parse_internship_form
from app.services.notifications import notify, notify_role
from app.services.settings import LABELS, get_all_settings, save_settings, validate_settings
from app.utils.decorators import role_required
from app.utils.validators import FormErrors, clean_str, password_problems, valid_email

bp = Blueprint("admin", __name__)


@bp.before_request
@role_required(Role.ADMIN)
def guard():
    return None


# ------------------------------------------------------------------ dashboard
@bp.route("/dashboard")
def dashboard():
    stats = {
        "students": StudentProfile.query.count(),
        "companies": CompanyProfile.query.count(),
        "pending_companies": CompanyProfile.query.filter_by(is_verified=False).count(),
        "internships": Internship.query.filter_by(status=InternshipStatus.PUBLISHED).count(),
        "seats": db.session.query(db.func.coalesce(db.func.sum(Internship.seats), 0))
        .filter(Internship.status == InternshipStatus.PUBLISHED).scalar(),
        "applications": Application.query.count(),
        "allocations": Allocation.query.filter_by(status=AllocationStatus.ACTIVE).count(),
    }
    runs = AllocationRun.query.order_by(AllocationRun.created_at.desc()).limit(5).all()
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(6).all()
    return render_template("admin/dashboard.html", stats=stats, runs=runs, logs=logs)


# ------------------------------------------------------------------ students
@bp.route("/students")
def students():
    q = StudentProfile.query.join(User)
    term = request.args.get("q", "").strip()
    if term:
        like = f"%{term[:80]}%"
        q = q.filter(db.or_(User.name.ilike(like), User.email.ilike(like), StudentProfile.roll_number.ilike(like),
                            StudentProfile.department.ilike(like)))
    if request.args.get("department"):
        q = q.filter(StudentProfile.department == request.args.get("department"))
    pagination = (q.order_by(User.name)).paginate(page=request.args.get("page", 1, type=int), per_page=15,
                             error_out=False)
    departments = [d for (d,) in db.session.query(StudentProfile.department).distinct() if d]
    return render_template("admin/students.html", pagination=pagination, departments=sorted(departments))


@bp.route("/students/<int:sid>")
def student_detail(sid):
    p = db.get_or_404(StudentProfile, sid)
    recs = match_service.recommendations(p, limit=5)
    db.session.commit()
    allocs = Allocation.query.filter_by(student_id=p.id).order_by(Allocation.created_at.desc()).all()
    open_internships = Internship.query.filter(
        Internship.status.in_([InternshipStatus.PUBLISHED, InternshipStatus.CLOSED])).order_by(Internship.title).all()
    return render_template("admin/student_detail.html", p=p, recs=recs, allocs=allocs,
                           internships=open_internships)


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
def toggle_user(uid):
    u = db.get_or_404(User, uid)
    if u.id == current_user.id:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(request.referrer or url_for("admin.dashboard"))
    u.is_active_flag = not u.is_active_flag
    log_action("user.toggle_active", "user", u.id, f"active={u.is_active_flag}")
    db.session.commit()
    flash(f"{u.name} is now {'active' if u.is_active_flag else 'deactivated'}.", "success")
    return redirect(request.referrer or url_for("admin.students"))


# ------------------------------------------------------------------ companies
@bp.route("/companies")
def companies():
    items = CompanyProfile.query.order_by(CompanyProfile.is_verified, CompanyProfile.company_name).all()
    return render_template("admin/companies.html", items=items)


@bp.route("/companies/new", methods=["GET", "POST"])
def new_company():
    if request.method == "POST":
        errors = FormErrors()
        email = clean_str(request.form.get("email")).lower()
        name = clean_str(request.form.get("contact_person"), 120)
        company_name = clean_str(request.form.get("company_name"), 150)
        password = request.form.get("password") or ""
        if not valid_email(email):
            errors.add("Valid email is required.")
        elif User.query.filter_by(email=email).first():
            errors.add("Email already in use.")
        if len(company_name) < 2:
            errors.add("Company name is required.")
        if len(name) < 2:
            errors.add("Contact person is required.")
        errors.extend(password_problems(password))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/company_form.html", c=None, form=request.form), 400
        u = User(email=email, name=name, role=Role.COMPANY)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        c = CompanyProfile(user_id=u.id, company_name=company_name, contact_person=name, is_verified=True,
                           industry=clean_str(request.form.get("industry"), 80) or None,
                           location=clean_str(request.form.get("location"), 120) or None,
                           website=clean_str(request.form.get("website"), 255) or None,
                           description=clean_str(request.form.get("description"), 5000) or None)
        db.session.add(c)
        log_action("company.create", "company", None, company_name)
        db.session.commit()
        flash(f"Company account for {company_name} created and verified.", "success")
        return redirect(url_for("admin.companies"))
    return render_template("admin/company_form.html", c=None, form=None)


@bp.route("/companies/<int:cid>/edit", methods=["GET", "POST"])
def edit_company(cid):
    c = db.get_or_404(CompanyProfile, cid)
    if request.method == "POST":
        name = clean_str(request.form.get("company_name"), 150)
        if len(name) < 2:
            flash("Company name is required.", "danger")
            return render_template("admin/company_form.html", c=c, form=request.form), 400
        c.company_name = name
        for f, n in (("industry", 80), ("location", 120), ("website", 255), ("contact_person", 120),
                     ("description", 5000)):
            setattr(c, f, clean_str(request.form.get(f), n) or None)
        log_action("company.update", "company", c.id, name)
        db.session.commit()
        flash("Company updated.", "success")
        return redirect(url_for("admin.companies"))
    return render_template("admin/company_form.html", c=c, form=None)


@bp.route("/companies/<int:cid>/verify", methods=["POST"])
def verify_company(cid):
    c = db.get_or_404(CompanyProfile, cid)
    c.is_verified = request.form.get("verified") == "1"
    notify(c.user, "Company verification updated",
           "Your company has been verified. You can now publish internships." if c.is_verified
           else "Your company verification was revoked. Contact the placement cell.", "info", "/company/internships")
    log_action("company.verify", "company", c.id, f"verified={c.is_verified}")
    db.session.commit()
    flash(f"{c.company_name} {'verified' if c.is_verified else 'unverified'}.", "success")
    return redirect(url_for("admin.companies"))


# ------------------------------------------------------------------ internships
@bp.route("/internships")
def internships():
    q = Internship.query.join(CompanyProfile)
    if request.args.get("status") in InternshipStatus.ALL:
        q = q.filter(Internship.status == request.args.get("status"))
    if request.args.get("q"):
        like = f"%{request.args.get('q').strip()[:80]}%"
        q = q.filter(db.or_(Internship.title.ilike(like), CompanyProfile.company_name.ilike(like)))
    pagination = (q.order_by(Internship.created_at.desc())).paginate(page=request.args.get("page", 1, type=int),
                             per_page=15, error_out=False)
    return render_template("admin/internships.html", pagination=pagination)


def _companies():
    return CompanyProfile.query.order_by(CompanyProfile.company_name).all()


@bp.route("/internships/new", methods=["GET", "POST"])
def new_internship():
    if request.method == "POST":
        data, errors = parse_internship_form(request.form)
        company = db.session.get(CompanyProfile, request.form.get("company_id", type=int) or 0)
        if company is None:
            errors.add("Please choose a company.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("internship_form.html", i=None, form=request.form, domains=DOMAINS,
                                   modes=WORK_MODES, companies=_companies(), back=url_for("admin.internships")), 400
        i = Internship(company_id=company.id,
                       status=InternshipStatus.PUBLISHED if request.form.get("publish") else InternshipStatus.DRAFT)
        db.session.add(i)
        apply_internship(i, data)
        db.session.flush()
        log_action("internship.create", "internship", i.id, i.title)
        db.session.commit()
        flash(f"Internship '{i.title}' created ({i.status}).", "success")
        return redirect(url_for("admin.internships"))
    return render_template("internship_form.html", i=None, form=None, domains=DOMAINS, modes=WORK_MODES,
                           companies=_companies(), back=url_for("admin.internships"))


@bp.route("/internships/<int:iid>/edit", methods=["GET", "POST"])
def edit_internship(iid):
    i = db.get_or_404(Internship, iid)
    if request.method == "POST":
        data, errors = parse_internship_form(request.form)
        company = db.session.get(CompanyProfile, request.form.get("company_id", type=int) or 0)
        if company is None:
            errors.add("Please choose a company.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("internship_form.html", i=i, form=request.form, domains=DOMAINS,
                                   modes=WORK_MODES, companies=_companies(), back=url_for("admin.internships")), 400
        i.company_id = company.id
        apply_internship(i, data)
        notified = notify_internship_update(i)
        log_action("internship.update", "internship", i.id, i.title)
        db.session.commit()
        flash("Internship updated." + (f" {notified} applicant(s) notified." if notified else ""), "success")
        return redirect(url_for("admin.internships"))
    return render_template("internship_form.html", i=i, form=None, domains=DOMAINS, modes=WORK_MODES,
                           companies=_companies(), back=url_for("admin.internships"))


@bp.route("/internships/<int:iid>/status", methods=["POST"])
def set_internship_status(iid):
    i = db.get_or_404(Internship, iid)
    status = request.form.get("status")
    if status not in InternshipStatus.ALL:
        abort(400)
    i.status = status
    log_action("internship.status", "internship", i.id, status)
    db.session.commit()
    flash(f"'{i.title}' is now {status}.", "success")
    return redirect(request.referrer or url_for("admin.internships"))


@bp.route("/internships/<int:iid>/applicants")
def applicants(iid):
    i = db.get_or_404(Internship, iid)
    rows = match_service.rank_applicants(i)
    db.session.commit()
    status = request.args.get("status")
    if status in AppStatus.ALL:
        rows = [r for r in rows if r[0].status == status]
    return render_template("applicants.html", i=i, rows=rows, base="admin", statuses=AppStatus.ALL,
                           transitions=AppStatus.ADMIN_TRANSITIONS)


# ------------------------------------------------------------------ applications
@bp.route("/applications")
def applications():
    q = Application.query.join(Internship).join(StudentProfile).join(User, StudentProfile.user_id == User.id)
    if request.args.get("status") in AppStatus.ALL:
        q = q.filter(Application.status == request.args.get("status"))
    if request.args.get("internship", type=int):
        q = q.filter(Application.internship_id == request.args.get("internship", type=int))
    if request.args.get("q"):
        like = f"%{request.args.get('q').strip()[:80]}%"
        q = q.filter(db.or_(User.name.ilike(like), Internship.title.ilike(like)))
    pagination = (q.order_by(Application.created_at.desc())).paginate(page=request.args.get("page", 1, type=int),
                             per_page=20, error_out=False)
    from app.models import MatchScore
    keys = [(a.student_id, a.internship_id) for a in pagination.items]
    scores = {}
    if keys:
        for m in MatchScore.query.filter(MatchScore.student_id.in_({k[0] for k in keys}),
                                         MatchScore.internship_id.in_({k[1] for k in keys})).all():
            scores[(m.student_id, m.internship_id)] = m
    all_internships = Internship.query.order_by(Internship.title).all()
    return render_template("admin/applications.html", pagination=pagination, scores=scores,
                           internships=all_internships, statuses=AppStatus.ALL)


@bp.route("/applications/<int:aid>")
def application_detail(aid):
    a = db.get_or_404(Application, aid)
    r = match_service.match_for(a.student, a.internship)
    db.session.commit()
    return render_template("application_detail.html", a=a, r=r, base="admin", transitions=AppStatus.ADMIN_TRANSITIONS)


@bp.route("/applications/<int:aid>/status", methods=["POST"])
def application_status(aid):
    a = db.get_or_404(Application, aid)
    try:
        update_status(a, request.form.get("status"), current_user, request.form.get("note", ""))
        flash(f"{a.student.user.name}: status changed to {a.status}.", "success")
    except ApplicationError as e:
        flash(e.message, "danger")
    return redirect(request.referrer or url_for("admin.applications"))


@bp.route("/applications/<int:aid>/delete", methods=["POST"])
def delete_application(aid):
    a = db.get_or_404(Application, aid)
    if a.status == AppStatus.ALLOCATED:
        flash("Cancel the allocation before deleting this application.", "warning")
        return redirect(request.referrer or url_for("admin.applications"))
    log_action("application.delete", "application", a.id, f"student={a.student_id} internship={a.internship_id}")
    db.session.delete(a)
    db.session.commit()
    flash("Application deleted.", "info")
    return redirect(url_for("admin.applications"))


# ------------------------------------------------------------------ allocation
@bp.route("/allocation")
def allocation():
    runs = AllocationRun.query.order_by(AllocationRun.created_at.desc()).limit(20).all()
    active = (Allocation.query.filter_by(status=AllocationStatus.ACTIVE)
              .order_by(Allocation.internship_id, Allocation.score.desc()).all())
    conflicts = alloc_service.find_conflicts()
    students = StudentProfile.query.join(User).order_by(User.name).all()
    internships = Internship.query.filter(
        Internship.status.in_([InternshipStatus.PUBLISHED, InternshipStatus.CLOSED])).order_by(Internship.title).all()
    pool = Application.query.filter(Application.status.in_(AppStatus.POOL)).count()
    return render_template("admin/allocation.html", runs=runs, active=active, conflicts=conflicts,
                           students=students, internships=internships, settings=get_all_settings(), pool=pool)


@bp.route("/allocation/preview", methods=["POST"])
def allocation_preview():
    run = alloc_service.create_preview(current_user)
    flash(f"Preview #{run.id} generated with {len(run.allocations)} proposed allocation(s). "
          "Review and confirm to make it final.", "info")
    return redirect(url_for("admin.run_detail", rid=run.id))


@bp.route("/allocation/runs/<int:rid>")
def run_detail(rid):
    run = db.get_or_404(AllocationRun, rid)
    allocs = sorted(run.allocations, key=lambda a: (a.internship.title, -(a.score or 0)))
    students = {s.id: s for s in StudentProfile.query.filter(
        StudentProfile.id.in_([u["student_id"] for u in run.summary.get("unallocated", [])] or [-1])).all()}
    return render_template("admin/run_detail.html", run=run, allocs=allocs, students=students)


@bp.route("/allocation/runs/<int:rid>/confirm", methods=["POST"])
def run_confirm(rid):
    run = db.get_or_404(AllocationRun, rid)
    try:
        confirmed, skipped = alloc_service.confirm_run(run, current_user)
        flash(f"Allocation confirmed: {confirmed} allocation(s) made"
              + (f", {skipped} skipped because data changed since the preview" if skipped else "") + ".", "success")
    except alloc_service.AllocationError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin.run_detail", rid=rid))


@bp.route("/allocation/runs/<int:rid>/discard", methods=["POST"])
def run_discard(rid):
    run = db.get_or_404(AllocationRun, rid)
    try:
        alloc_service.discard_run(run, current_user)
        flash("Preview discarded.", "info")
    except alloc_service.AllocationError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin.allocation"))


@bp.route("/allocation/runs/<int:rid>/report.csv")
def run_report(rid):
    run = db.get_or_404(AllocationRun, rid)
    rows = [["Run", "Status", "Student", "Email", "Department", "CGPA", "Internship", "Company", "Score",
             "Allocation status", "Note"]]
    for a in sorted(run.allocations, key=lambda a: (a.internship.title, -(a.score or 0))):
        s = a.student
        rows.append([run.id, run.status, s.user.name, s.user.email, s.department or "", s.cgpa or "",
                     a.internship.title, a.internship.company.company_name, a.score, a.status, a.note or ""])
    for u in run.summary.get("unallocated", []):
        s = db.session.get(StudentProfile, u["student_id"])
        if s:
            rows.append([run.id, run.status, s.user.name, s.user.email, s.department or "", s.cgpa or "",
                         "", "", "", "unallocated", u["reason"]])
    return _csv(rows, f"allocation_run_{run.id}.csv")


@bp.route("/allocations/<int:alloc_id>/cancel", methods=["POST"])
def cancel_allocation(alloc_id):
    a = db.get_or_404(Allocation, alloc_id)
    try:
        alloc_service.cancel_allocation(a, current_user, clean_str(request.form.get("reason"), 200))
        flash("Allocation cancelled; the application is back in the allocation pool.", "info")
    except alloc_service.AllocationError as e:
        flash(str(e), "danger")
    return redirect(request.referrer or url_for("admin.allocation"))


@bp.route("/allocation/manual", methods=["POST"])
def manual_allocation():
    s = db.session.get(StudentProfile, request.form.get("student_id", type=int) or 0)
    i = db.session.get(Internship, request.form.get("internship_id", type=int) or 0)
    if s is None or i is None:
        flash("Choose both a student and an internship.", "danger")
    else:
        try:
            alloc_service.manual_allocate(s, i, current_user, clean_str(request.form.get("note"), 200))
            flash(f"{s.user.name} allocated to {i.title}.", "success")
        except alloc_service.AllocationError as e:
            flash(str(e), "danger")
    return redirect(request.referrer or url_for("admin.allocation"))


# ------------------------------------------------------------------ reports
def _csv(rows, filename):
    buf = io.StringIO()
    writer = csv.writer(buf)
    for r in rows:
        writer.writerow([_safe_cell(c) for c in r])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _safe_cell(value):
    """Neutralise spreadsheet formula injection."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@bp.route("/reports")
def reports():
    return render_template("admin/reports.html")


@bp.route("/reports/<name>.csv")
def report_csv(name):
    if name == "applications":
        rows = [["ID", "Student", "Email", "Department", "CGPA", "Internship", "Company", "Status", "Preference",
                 "Applied (UTC)"]]
        for a in Application.query.order_by(Application.created_at).all():
            s = a.student
            rows.append([a.id, s.user.name, s.user.email, s.department or "", s.cgpa or "", a.internship.title,
                         a.internship.company.company_name, a.status, a.preference_rank,
                         a.created_at.strftime("%Y-%m-%d %H:%M")])
    elif name == "allocations":
        rows = [["ID", "Run", "Student", "Email", "Internship", "Company", "Score", "Status", "Created (UTC)"]]
        for a in Allocation.query.filter(Allocation.status.in_([AllocationStatus.ACTIVE, AllocationStatus.CANCELLED])
                                         ).order_by(Allocation.created_at).all():
            rows.append([a.id, a.run_id or "manual", a.student.user.name, a.student.user.email, a.internship.title,
                         a.internship.company.company_name, a.score, a.status, a.created_at.strftime("%Y-%m-%d %H:%M")])
    elif name == "students":
        rows = [["ID", "Name", "Email", "Roll no", "Department", "Year", "CGPA", "Skills", "Profile %",
                 "Applications", "Active allocations"]]
        for s in StudentProfile.query.all():
            active = sum(1 for a in Allocation.query.filter_by(student_id=s.id, status=AllocationStatus.ACTIVE))
            rows.append([s.id, s.user.name, s.user.email, s.roll_number or "", s.department or "",
                         s.year_of_study or "", s.cgpa or "", "; ".join(s.skill_names), s.completion_percent(),
                         len(s.applications), active])
    elif name == "internships":
        rows = [["ID", "Title", "Company", "Domain", "Status", "Seats", "Allocated", "Applications", "Min CGPA",
                 "Required skills", "Deadline"]]
        for i in Internship.query.all():
            rows.append([i.id, i.title, i.company.company_name, i.domain, i.status, i.seats,
                         i.active_allocation_count(), len(i.applications), i.min_cgpa or "",
                         "; ".join(i.required_skills), i.deadline.isoformat() if i.deadline else ""])
    else:
        abort(404)
    log_action("report.download", "report", None, name)
    db.session.commit()
    return _csv(rows, f"{name}.csv")


@bp.route("/feedback")
def feedback():
    items = Feedback.query.order_by(Feedback.created_at.desc()).all()
    avg = round(sum(f.rating for f in items) / len(items), 2) if items else None
    return render_template("admin/feedback.html", items=items, avg=avg)


# ------------------------------------------------------------------ announcements / settings / audit
@bp.route("/announcements", methods=["GET", "POST"])
def announcements():
    if request.method == "POST":
        title = clean_str(request.form.get("title"), 150)
        body = clean_str(request.form.get("body"), 5000)
        audience = request.form.get("audience", "all")
        if audience not in ("all", Role.STUDENT, Role.COMPANY) or len(title) < 3 or len(body) < 5:
            flash("Title (3+ chars), message (5+ chars) and a valid audience are required.", "danger")
        else:
            a = Announcement(title=title, body=body, audience=audience, created_by_id=current_user.id)
            db.session.add(a)
            count = notify_role(audience, f"Announcement: {title}", body, "announcement")
            log_action("announcement.create", "announcement", None, title)
            db.session.commit()
            flash(f"Announcement sent to {count} user(s).", "success")
            return redirect(url_for("admin.announcements"))
    items = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template("admin/announcements.html", items=items)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        if request.form.get("action") == "recompute":
            n = match_service.refresh_all()
            log_action("scores.recompute", "settings", None, f"{n} applications")
            db.session.commit()
            flash(f"Match scores recomputed for {n} application(s).", "success")
            return redirect(url_for("admin.settings"))
        clean, errors = validate_settings({k: request.form.get(k) for k in LABELS if request.form.get(k) is not None})
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            save_settings(clean)
            log_action("settings.update", "settings", None, ", ".join(f"{k}={v}" for k, v in clean.items()))
            db.session.commit()
            match_service.refresh_all()
            db.session.commit()
            flash("Settings saved and cached match scores recomputed.", "success")
            return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", values=get_all_settings(), labels=LABELS)


@bp.route("/audit")
def audit():
    q = AuditLog.query
    if request.args.get("action"):
        q = q.filter(AuditLog.action.ilike(f"%{request.args.get('action')[:40]}%"))
    pagination = (q.order_by(AuditLog.created_at.desc())).paginate(page=request.args.get("page", 1, type=int),
                             per_page=25, error_out=False)
    return render_template("admin/audit.html", pagination=pagination)
