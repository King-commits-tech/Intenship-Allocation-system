"""JSON REST API. Authentication uses the same secure session cookie as the web UI.

State-changing requests (POST/PATCH/DELETE) require the CSRF token in an ``X-CSRFToken`` header;
obtain it from ``GET /api/csrf-token``.
"""
from collections import Counter
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_user, logout_user
from flask_wtf.csrf import generate_csrf

from app.extensions import db
from app.models import (DOMAINS, Allocation, AllocationRun, AllocationStatus, Application, AppStatus,
                        Internship, InternshipSkill, InternshipStatus, MatchScore, Notification, Role, Skill,
                        StudentProfile, User, utcnow)
from app.services import allocation as alloc_service
from app.services import match_service
from app.services.applications import ApplicationError, apply as apply_service, update_status
from app.utils.decorators import role_required

bp = Blueprint("api", __name__)


def err(message, status):
    return jsonify({"error": message, "status": status}), status


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ meta / auth
@bp.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "ok"})
    except Exception:  # noqa: BLE001
        return jsonify({"status": "degraded", "database": "unavailable"}), 503


@bp.route("/csrf-token")
def csrf_token():
    return jsonify({"csrf_token": generate_csrf()})


@bp.route("/auth/login", methods=["POST"])
def api_login():
    data = body()
    if data is None:
        return err("JSON body required.", 400)
    user = User.query.filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if user is None or user.is_locked() or not user.is_active:
        return err("Invalid credentials or account unavailable.", 401)
    if not user.check_password(str(data.get("password", ""))):
        user.register_failed_login(current_app.config["LOGIN_MAX_ATTEMPTS"], current_app.config["LOGIN_LOCK_MINUTES"])
        db.session.commit()
        return err("Invalid credentials or account unavailable.", 401)
    user.register_successful_login()
    db.session.commit()
    login_user(user)
    return jsonify({"user": user.to_dict()})


@bp.route("/auth/logout", methods=["POST"])
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@bp.route("/me")
@role_required(*Role.ALL)
def me():
    data = current_user.to_dict()
    if current_user.is_student:
        data["profile"] = current_user.student_profile.to_dict()
    elif current_user.is_company:
        data["profile"] = current_user.company_profile.to_dict()
    data["unread_notifications"] = current_user.unread_count()
    return jsonify(data)


# ------------------------------------------------------------------ internships
@bp.route("/internships")
@role_required(*Role.ALL)
def list_internships():
    q = Internship.query
    if current_user.is_admin:
        if request.args.get("status") in InternshipStatus.ALL:
            q = q.filter(Internship.status == request.args.get("status"))
    elif current_user.is_company:
        q = q.filter(Internship.company_id == current_user.company_profile.id)
    else:
        q = q.filter(Internship.status == InternshipStatus.PUBLISHED)
    if request.args.get("q"):
        like = f"%{request.args.get('q').strip()[:80]}%"
        q = q.filter(db.or_(Internship.title.ilike(like), Internship.description.ilike(like)))
    if request.args.get("domain") in DOMAINS:
        q = q.filter(Internship.domain == request.args.get("domain"))
    if request.args.get("skill"):
        q = q.join(InternshipSkill).join(Skill).filter(Skill.name.ilike(request.args.get("skill").strip()[:60]))
    per_page = min(50, max(1, request.args.get("per_page", 10, type=int)))
    page = max(1, request.args.get("page", 1, type=int))
    p = (q.order_by(Internship.created_at.desc())).paginate(page=page, per_page=per_page, error_out=False)
    items = [i.to_dict(include_description=False) for i in p.items]
    if current_user.is_student and p.items:
        results = match_service.compute([current_user.student_profile], p.items)
        db.session.commit()
        for d in items:
            r = results[(current_user.student_profile.id, d["id"])]
            d["match_score"], d["eligible"] = r["total"], r["eligible"]
    return jsonify({"items": items, "page": p.page, "pages": p.pages, "total": p.total})


def _visible_internship(iid):
    i = db.session.get(Internship, iid)
    if i is None:
        return None
    if current_user.is_admin:
        return i
    if current_user.is_company:
        return i if i.company_id == current_user.company_profile.id else None
    return i if i.status != InternshipStatus.DRAFT else None


@bp.route("/internships/<int:iid>")
@role_required(*Role.ALL)
def get_internship(iid):
    i = _visible_internship(iid)
    if i is None:
        return err("Internship not found.", 404)
    data = i.to_dict()
    if current_user.is_student:
        data["match"] = match_service.match_for(current_user.student_profile, i)
        db.session.commit()
    return jsonify(data)


@bp.route("/internships/<int:iid>/rankings")
@role_required(Role.ADMIN, Role.COMPANY)
def internship_rankings(iid):
    i = _visible_internship(iid)
    if i is None:
        return err("Internship not found.", 404)
    rows = match_service.rank_applicants(i)
    db.session.commit()
    return jsonify({"internship_id": i.id, "seats": i.seats, "seats_left": i.seats_left(), "rankings": [
        {"rank": n + 1, "application_id": a.id, "student_id": a.student_id, "student_name": a.student.user.name,
         "status": a.status, "score": r["total"], "eligible": r["eligible"], "components": r["components"],
         "matched_skills": r["matched_skills"], "missing_required": r["missing_required"]}
        for n, (a, r) in enumerate(rows)]})


# ------------------------------------------------------------------ student matching
@bp.route("/recommendations")
@role_required(Role.STUDENT)
def recommendations():
    limit = min(50, max(1, request.args.get("limit", 10, type=int)))
    recs = match_service.recommendations(current_user.student_profile, limit=limit,
                                         include_ineligible=request.args.get("all") == "1")
    db.session.commit()
    return jsonify({"items": [{"internship": i.to_dict(include_description=False), "match": r} for i, r in recs],
                    "disclaimer": "Scores assist decision-making and do not guarantee selection."})


@bp.route("/match/<int:iid>")
@role_required(Role.STUDENT)
def match(iid):
    i = _visible_internship(iid)
    if i is None:
        return err("Internship not found.", 404)
    r = match_service.match_for(current_user.student_profile, i)
    db.session.commit()
    return jsonify(r)


# ------------------------------------------------------------------ applications
@bp.route("/applications", methods=["GET"])
@role_required(*Role.ALL)
def list_applications():
    q = Application.query
    if current_user.is_student:
        q = q.filter(Application.student_id == current_user.student_profile.id)
    elif current_user.is_company:
        q = q.join(Internship).filter(Internship.company_id == current_user.company_profile.id)
    if request.args.get("status") in AppStatus.ALL:
        q = q.filter(Application.status == request.args.get("status"))
    if request.args.get("internship_id", type=int):
        q = q.filter(Application.internship_id == request.args.get("internship_id", type=int))
    return jsonify({"items": [a.to_dict() for a in q.order_by(Application.created_at.desc()).limit(500).all()]})


@bp.route("/applications", methods=["POST"])
@role_required(Role.STUDENT)
def create_application():
    data = body()
    if data is None or not isinstance(data.get("internship_id"), int):
        return err("JSON body with integer 'internship_id' is required.", 400)
    i = db.session.get(Internship, data["internship_id"])
    if i is None or i.status == InternshipStatus.DRAFT:
        return err("Internship not found.", 404)
    try:
        app_, r = apply_service(current_user.student_profile, i, data.get("preference_rank"),
                                str(data.get("cover_note") or ""))
    except ApplicationError as e:
        return err(e.message, e.status)
    return jsonify({"application": app_.to_dict(), "match": r}), 201


@bp.route("/applications/<int:aid>/status", methods=["PATCH", "POST"])
@role_required(Role.ADMIN, Role.COMPANY)
def application_status(aid):
    a = db.session.get(Application, aid)
    if a is None:
        return err("Application not found.", 404)
    if current_user.is_company and a.internship.company_id != current_user.company_profile.id:
        return err("Application not found.", 404)
    data = body()
    if data is None or "status" not in data:
        return err("JSON body with 'status' is required.", 400)
    try:
        update_status(a, str(data["status"]), current_user, str(data.get("note") or ""))
    except ApplicationError as e:
        return err(e.message, e.status)
    return jsonify({"application": a.to_dict()})


# ------------------------------------------------------------------ notifications
@bp.route("/notifications")
@role_required(*Role.ALL)
def notifications():
    q = current_user.notifications.order_by(Notification.created_at.desc())
    if request.args.get("unread") == "1":
        q = q.filter_by(is_read=False)
    return jsonify({"items": [n.to_dict() for n in q.limit(50).all()], "unread": current_user.unread_count()})


@bp.route("/notifications/<int:nid>/read", methods=["POST"])
@role_required(*Role.ALL)
def notification_read(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first()
    if n is None:
        return err("Notification not found.", 404)
    n.is_read = True
    db.session.commit()
    return jsonify({"ok": True, "unread": current_user.unread_count()})


@bp.route("/notifications/read-all", methods=["POST"])
@role_required(*Role.ALL)
def notifications_read_all():
    current_user.notifications.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True, "unread": 0})


# ------------------------------------------------------------------ allocation
@bp.route("/allocation/preview", methods=["POST"])
@role_required(Role.ADMIN)
def allocation_preview():
    run = alloc_service.create_preview(current_user)
    return jsonify({"run_id": run.id, "status": run.status, "summary": run.summary,
                    "proposals": [a.to_dict() for a in run.allocations]}), 201


@bp.route("/allocation/runs")
@role_required(Role.ADMIN)
def allocation_runs():
    runs = AllocationRun.query.order_by(AllocationRun.created_at.desc()).limit(50).all()
    return jsonify({"items": [{"id": r.id, "status": r.status, "created_at": r.created_at.isoformat(),
                               "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                               "summary": r.summary, "params": r.params} for r in runs]})


@bp.route("/allocation/runs/<int:rid>/confirm", methods=["POST"])
@role_required(Role.ADMIN)
def allocation_confirm(rid):
    run = db.session.get(AllocationRun, rid)
    if run is None:
        return err("Allocation run not found.", 404)
    try:
        confirmed, skipped = alloc_service.confirm_run(run, current_user)
    except alloc_service.AllocationError as e:
        return err(str(e), 409)
    return jsonify({"run_id": run.id, "status": run.status, "confirmed": confirmed, "skipped": skipped})


@bp.route("/allocation/runs/<int:rid>/discard", methods=["POST"])
@role_required(Role.ADMIN)
def allocation_discard(rid):
    run = db.session.get(AllocationRun, rid)
    if run is None:
        return err("Allocation run not found.", 404)
    try:
        alloc_service.discard_run(run, current_user)
    except alloc_service.AllocationError as e:
        return err(str(e), 409)
    return jsonify({"run_id": run.id, "status": run.status})


@bp.route("/allocations")
@role_required(*Role.ALL)
def allocations():
    q = Allocation.query.filter(Allocation.status == AllocationStatus.ACTIVE)
    if current_user.is_student:
        q = q.filter(Allocation.student_id == current_user.student_profile.id)
    elif current_user.is_company:
        q = q.join(Internship).filter(Internship.company_id == current_user.company_profile.id)
    return jsonify({"items": [a.to_dict() for a in q.all()]})


@bp.route("/allocations/<int:alloc_id>/cancel", methods=["POST"])
@role_required(Role.ADMIN)
def allocation_cancel(alloc_id):
    a = db.session.get(Allocation, alloc_id)
    if a is None:
        return err("Allocation not found.", 404)
    data = body() or {}
    try:
        alloc_service.cancel_allocation(a, current_user, str(data.get("reason") or "")[:200])
    except alloc_service.AllocationError as e:
        return err(str(e), 409)
    return jsonify({"allocation": a.to_dict()})


# ------------------------------------------------------------------ chart statistics (live DB data)
def _status_counts(apps):
    c = Counter(a.status for a in apps)
    return {s: c.get(s, 0) for s in AppStatus.ALL}


def _timeline(apps, days=14):
    today = utcnow().date()
    buckets = {(today - timedelta(days=d)).isoformat(): 0 for d in range(days - 1, -1, -1)}
    for a in apps:
        k = a.created_at.date().isoformat()
        if k in buckets:
            buckets[k] += 1
    return {"labels": list(buckets), "values": list(buckets.values())}


@bp.route("/stats/admin")
@role_required(Role.ADMIN)
def stats_admin():
    published = Internship.query.filter_by(status=InternshipStatus.PUBLISHED).all()
    by_domain = Counter()
    seats_by_domain = Counter()
    for i in published:
        by_domain[i.domain] += 1
        seats_by_domain[i.domain] += i.seats
    skill_demand = Counter()
    for i in published:
        for s in i.required_skills:
            skill_demand[s] += 1
    apps = Application.query.all()
    alloc_rows = []
    for i in Internship.query.filter(Internship.status != InternshipStatus.DRAFT).all():
        alloc_rows.append((i.title[:28], i.seats, i.active_allocation_count(), len(i.applications)))
    alloc_rows.sort(key=lambda r: -r[3])
    alloc_rows = alloc_rows[:10]
    scores = [m.total_score for m in MatchScore.query.join(
        Application, db.and_(Application.student_id == MatchScore.student_id,
                             Application.internship_id == MatchScore.internship_id)).all()]
    bins = ["0-20", "20-40", "40-60", "60-80", "80-100"]
    dist = Counter(min(4, int(s // 20)) for s in scores)
    student_skill = Counter()
    for sp in StudentProfile.query.all():
        for s in sp.skill_names:
            student_skill[s] += 1
    top_demand = skill_demand.most_common(10)
    return jsonify({
        "internships_by_domain": {"labels": list(by_domain), "values": list(by_domain.values()),
                                  "seats": [seats_by_domain[d] for d in by_domain]},
        "application_status": _status_counts(apps),
        "allocation_by_internship": {"labels": [r[0] for r in alloc_rows], "seats": [r[1] for r in alloc_rows],
                                     "allocated": [r[2] for r in alloc_rows],
                                     "applications": [r[3] for r in alloc_rows]},
        "skill_demand": {"labels": [s for s, _ in top_demand], "demand": [c for _, c in top_demand],
                         "supply": [student_skill.get(s, 0) for s, _ in top_demand]},
        "score_distribution": {"labels": bins, "values": [dist.get(n, 0) for n in range(5)]},
        "applications_timeline": _timeline(apps),
    })


@bp.route("/stats/company")
@role_required(Role.COMPANY)
def stats_company():
    internships = current_user.company_profile.internships
    apps = [a for i in internships for a in i.applications]
    keys = [(a.student_id, a.internship_id) for a in apps]
    scores = []
    if keys:
        for m in MatchScore.query.filter(MatchScore.internship_id.in_([i.id for i in internships])).all():
            if (m.student_id, m.internship_id) in set(keys):
                scores.append(m.total_score)
    dist = Counter(min(4, int(s // 20)) for s in scores)
    return jsonify({
        "applications_by_internship": {"labels": [i.title[:28] for i in internships],
                                       "values": [len(i.applications) for i in internships],
                                       "seats": [i.seats for i in internships],
                                       "allocated": [i.active_allocation_count() for i in internships]},
        "application_status": _status_counts(apps),
        "score_distribution": {"labels": ["0-20", "20-40", "40-60", "60-80", "80-100"],
                               "values": [dist.get(n, 0) for n in range(5)]},
    })


@bp.route("/stats/student")
@role_required(Role.STUDENT)
def stats_student():
    p = current_user.student_profile
    recs = match_service.recommendations(p, limit=10, include_ineligible=True)
    db.session.commit()
    gaps = Counter()
    for _, r in recs:
        for s in r["missing_required"] + r["missing_preferred"]:
            gaps[s] += 1
    top = gaps.most_common(8)
    return jsonify({
        "application_status": _status_counts(p.applications),
        "skill_gaps": {"labels": [s for s, _ in top], "values": [c for _, c in top]},
        "top_matches": {"labels": [i.title[:24] for i, _ in recs[:6]], "values": [r["total"] for _, r in recs[:6]]},
    })


@bp.route("/students/<int:sid>")
@role_required(Role.ADMIN)
def student(sid):
    s = db.session.get(StudentProfile, sid)
    if s is None:
        return err("Student not found.", 404)
    return jsonify(s.to_dict())
