from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models import (DOMAINS, WORK_MODES, Allocation, AllocationStatus, Application, AppStatus, Feedback,
                        Internship, InternshipStatus, Notification, Resume, Role)
from app.services import match_service
from app.services.applications import ApplicationError, apply as apply_service, withdraw as withdraw_service
from app.services.forms import add_student_skills, set_student_skills
from app.services.resume import ResumeError, delete_file, process_pdf, resolve_path, store_file, validate_upload
from app.services.skills import all_skill_names, parse_skill_list
from app.utils.decorators import role_required
from app.utils.validators import FormErrors, clean_str, opt_float, opt_int

bp = Blueprint("student", __name__)


@bp.before_request
@role_required(Role.STUDENT)
def guard():
    if current_user.student_profile is None:
        abort(403)


def me():
    return current_user.student_profile


@bp.route("/dashboard")
def dashboard():
    p = me()
    recs = match_service.recommendations(p, limit=3)
    db.session.commit()
    counts = {s: 0 for s in AppStatus.ALL}
    for a in p.applications:
        counts[a.status] += 1
    allocations = Allocation.query.filter_by(student_id=p.id, status=AllocationStatus.ACTIVE).all()
    notes = current_user.notifications.order_by(Notification.created_at.desc()).limit(5).all()
    return render_template("student/dashboard.html", p=p, recs=recs, counts=counts, allocations=allocations,
                           notes=notes)


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    p = me()
    if request.method == "POST":
        errors = FormErrors()
        name = clean_str(request.form.get("name"), 120)
        if len(name) < 2:
            errors.add("Name is required.")
        fields = {
            "roll_number": clean_str(request.form.get("roll_number"), 40) or None,
            "phone": clean_str(request.form.get("phone"), 30) or None,
            "degree": clean_str(request.form.get("degree"), 80) or None,
            "department": clean_str(request.form.get("department"), 80) or None,
            "year_of_study": opt_int(request.form.get("year_of_study"), "Year of study", errors, 1, 6),
            "graduation_year": opt_int(request.form.get("graduation_year"), "Graduation year", errors, 2000, 2100),
            "cgpa": opt_float(request.form.get("cgpa"), "CGPA", errors, 0, 10),
            "percentage": opt_float(request.form.get("percentage"), "Percentage", errors, 0, 100),
            "interests": clean_str(request.form.get("interests"), 2000) or None,
            "projects": clean_str(request.form.get("projects"), 5000) or None,
            "experience": clean_str(request.form.get("experience"), 5000) or None,
            "certifications": clean_str(request.form.get("certifications"), 2000) or None,
            "preferred_domain": clean_str(request.form.get("preferred_domain"), 80) or None,
            "preferred_location": clean_str(request.form.get("preferred_location"), 80) or None,
        }
        if fields["preferred_domain"] and fields["preferred_domain"] not in DOMAINS:
            errors.add("Please choose a valid preferred domain.")
        skills = parse_skill_list(request.form.get("skills"))
        if len(skills) > 60:
            errors.add("Please list at most 60 skills.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("student/profile.html", p=p, domains=DOMAINS, skill_names=all_skill_names(),
                                   form=request.form), 400
        current_user.name = name
        for k, v in fields.items():
            setattr(p, k, v)
        set_student_skills(p, skills)
        db.session.commit()
        flash("Profile saved. Your recommendations have been updated.", "success")
        return redirect(url_for("student.profile"))
    return render_template("student/profile.html", p=p, domains=DOMAINS, skill_names=all_skill_names(), form=None)


@bp.route("/resume", methods=["POST"])
def upload_resume():
    p = me()
    try:
        original, data = validate_upload(request.files.get("resume"))
    except ResumeError as e:
        flash(str(e), "danger")
        return redirect(url_for("student.profile") + "#resume")
    stored = store_file(data)
    result = process_pdf(resolve_path(stored))
    if p.resume:
        delete_file(p.resume.stored_filename)
        db.session.delete(p.resume)
        db.session.flush()
    p.resume = Resume(original_filename=original, stored_filename=stored, size_bytes=len(data),
                      extracted_text=result["text"] or None, extracted_skills=",".join(result["skills"]),
                      extraction_status=result["status"], extraction_message=result["message"])
    added = add_student_skills(p, result["skills"], source="resume")
    db.session.commit()
    if result["status"] == "ok":
        flash(f"Resume uploaded. {len(result['skills'])} skill(s) detected"
              + (f", {len(added)} added to your profile" if added else "")
              + ". Please review your skills below and remove anything incorrect.", "success")
    else:
        flash("Resume saved, but: " + result["message"], "warning")
    return redirect(url_for("student.profile") + "#skills")


@bp.route("/resume/delete", methods=["POST"])
def delete_resume():
    p = me()
    if p.resume:
        delete_file(p.resume.stored_filename)
        db.session.delete(p.resume)
        db.session.commit()
        flash("Resume removed.", "info")
    return redirect(url_for("student.profile") + "#resume")


def _filtered_internships():
    args = request.args
    q = Internship.query.filter_by(status=InternshipStatus.PUBLISHED)
    if args.get("q"):
        like = f"%{args.get('q').strip()[:80]}%"
        q = q.filter(db.or_(Internship.title.ilike(like), Internship.description.ilike(like),
                            Internship.location.ilike(like)))
    if args.get("domain") in DOMAINS:
        q = q.filter(Internship.domain == args.get("domain"))
    if args.get("mode") in WORK_MODES:
        q = q.filter(Internship.work_mode == args.get("mode"))
    if args.get("paid") == "1":
        q = q.filter(Internship.stipend.isnot(None), Internship.stipend > 0)
    return [i for i in q.all() if i.is_open]


@bp.route("/internships")
def internships():
    p = me()
    items = _filtered_internships()
    results = match_service.compute([p], items)
    db.session.commit()
    rows = [(i, results[(p.id, i.id)]) for i in items]
    if request.args.get("eligible") == "1":
        rows = [r for r in rows if r[1]["eligible"]]
    sort = request.args.get("sort", "match")
    if sort == "newest":
        rows.sort(key=lambda r: r[0].created_at, reverse=True)
    elif sort == "deadline":
        rows.sort(key=lambda r: (r[0].deadline is None, r[0].deadline or 0))
    elif sort == "stipend":
        rows.sort(key=lambda r: -(r[0].stipend or 0))
    else:
        rows.sort(key=lambda r: (not r[1]["eligible"], -r[1]["total"]))
    per_page = current_app.config["PAGE_SIZE"]
    page = max(1, request.args.get("page", 1, type=int))
    pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(page, pages)
    applied = {a.internship_id: a for a in p.applications}
    return render_template("student/internships.html", rows=rows[(page - 1) * per_page: page * per_page],
                           total=len(rows), page=page, pages=pages, domains=DOMAINS, modes=WORK_MODES,
                           applied=applied)


@bp.route("/internships/<int:iid>")
def internship_detail(iid):
    p = me()
    i = db.get_or_404(Internship, iid)
    if i.status == InternshipStatus.DRAFT:
        abort(404)
    result = match_service.match_for(p, i)
    db.session.commit()
    application = Application.query.filter_by(student_id=p.id, internship_id=i.id).first()
    next_rank = len(p.applications) + 1
    return render_template("student/internship_detail.html", i=i, r=result, application=application,
                           next_rank=next_rank)


@bp.route("/internships/<int:iid>/apply", methods=["POST"])
def apply(iid):
    p = me()
    i = db.get_or_404(Internship, iid)
    try:
        apply_service(p, i, request.form.get("preference_rank"), request.form.get("cover_note"))
        flash(f"Application for {i.title} submitted.", "success")
        return redirect(url_for("student.applications"))
    except ApplicationError as e:
        flash(e.message, "danger")
        return redirect(url_for("student.internship_detail", iid=iid))


@bp.route("/applications")
def applications():
    p = me()
    apps = sorted(p.applications, key=lambda a: (a.preference_rank, a.created_at))
    scores = {}
    if apps:
        for a in apps:
            scores[a.id] = match_service.match_for(p, a.internship)["total"]
        db.session.commit()
    return render_template("student/applications.html", apps=apps, scores=scores)


@bp.route("/applications/<int:aid>/withdraw", methods=["POST"])
def withdraw(aid):
    p = me()
    a = Application.query.filter_by(id=aid, student_id=p.id).first_or_404()
    try:
        withdraw_service(a, p)
        flash("Application withdrawn.", "info")
    except ApplicationError as e:
        flash(e.message, "danger")
    return redirect(url_for("student.applications"))


@bp.route("/applications/<int:aid>/preference", methods=["POST"])
def set_preference(aid):
    p = me()
    a = Application.query.filter_by(id=aid, student_id=p.id).first_or_404()
    errors = FormErrors()
    rank = opt_int(request.form.get("preference_rank"), "Preference", errors, 1, 50)
    if errors or rank is None:
        flash(errors[0] if errors else "Preference is required.", "danger")
    elif a.status not in AppStatus.POOL:
        flash("Preference can only be changed for pending applications.", "warning")
    else:
        a.preference_rank = rank
        db.session.commit()
        flash("Preference updated.", "success")
    return redirect(url_for("student.applications"))


@bp.route("/recommendations")
def recommendations():
    p = me()
    show_all = request.args.get("all") == "1"
    recs = match_service.recommendations(p, include_ineligible=show_all)
    db.session.commit()
    applied = {a.internship_id: a for a in p.applications}
    return render_template("student/recommendations.html", recs=recs, p=p, applied=applied, show_all=show_all)


@bp.route("/allocations")
def allocations():
    p = me()
    allocs = (Allocation.query.filter(Allocation.student_id == p.id,
                                      Allocation.status.in_([AllocationStatus.ACTIVE, AllocationStatus.CANCELLED]))
              .order_by(Allocation.created_at.desc()).all())
    feedback = {f.internship_id: f for f in Feedback.query.filter_by(student_id=p.id).all()}
    return render_template("student/allocations.html", allocs=allocs, feedback=feedback)


@bp.route("/feedback/<int:iid>", methods=["POST"])
def feedback(iid):
    p = me()
    alloc = Allocation.query.filter_by(student_id=p.id, internship_id=iid, status=AllocationStatus.ACTIVE).first()
    if alloc is None:
        flash("You can only give feedback for internships you were allocated to.", "danger")
        return redirect(url_for("student.allocations"))
    errors = FormErrors()
    rating = opt_int(request.form.get("rating"), "Overall rating", errors, 1, 5)
    learning = opt_int(request.form.get("learning_rating"), "Learning rating", errors, 1, 5)
    if rating is None and not errors:
        errors.add("Overall rating is required.")
    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("student.allocations"))
    fb = Feedback.query.filter_by(student_id=p.id, internship_id=iid).first() or Feedback(
        student_id=p.id, internship_id=iid, rating=rating)
    fb.rating, fb.learning_rating = rating, learning
    fb.comments = clean_str(request.form.get("comments"), 3000) or None
    db.session.add(fb)
    db.session.commit()
    flash("Thank you for your feedback!", "success")
    return redirect(url_for("student.allocations"))
