"""Database layer around the matching engine: builds documents, caches MatchScore rows."""
import json

from app.extensions import db
from app.models import (Application, Internship, InternshipStatus, MatchScore, StudentProfile, utcnow)
from app.services.matching import InternshipDoc, StudentDoc, score_matrix
from app.services.settings import get_weights


def student_doc(p: StudentProfile) -> StudentDoc:
    return StudentDoc(
        id=p.id, skills=p.skill_names,
        resume_text=(p.resume.extracted_text if p.resume and p.resume.extracted_text else ""),
        projects=p.projects or "", experience=p.experience or "", certifications=p.certifications or "",
        interests=p.interests or "", preferred_domain=p.preferred_domain or "",
        preferred_location=p.preferred_location or "", cgpa=p.cgpa, percentage=p.percentage,
        department=p.department or "", year_of_study=p.year_of_study,
    )


def internship_doc(i: Internship) -> InternshipDoc:
    return InternshipDoc(
        id=i.id, title=i.title, description=i.description or "", domain=i.domain or "",
        location=i.location or "", work_mode=i.work_mode or "", required_skills=i.required_skills,
        preferred_skills=i.preferred_skills, min_cgpa=i.min_cgpa, departments=i.department_list,
        years=i.year_list,
    )


def _store(results):
    """Upsert MatchScore rows for the given results (caller commits)."""
    if not results:
        return
    pairs = list(results)
    sids = {p[0] for p in pairs}
    iids = {p[1] for p in pairs}
    existing = {(m.student_id, m.internship_id): m for m in MatchScore.query.filter(
        MatchScore.student_id.in_(sids), MatchScore.internship_id.in_(iids)).all()}
    now = utcnow()
    for key, r in results.items():
        row = existing.get(key)
        if row is None:
            row = MatchScore(student_id=key[0], internship_id=key[1])
            db.session.add(row)
        row.total_score = r["total"]
        row.skill_score = r["components"]["skills"]
        row.project_score = r["components"]["projects"]
        row.interest_score = r["components"]["interests"]
        row.academic_score = r["components"]["academics"]
        row.is_eligible = r["eligible"]
        row.explanation_json = json.dumps(r)
        row.computed_at = now


def compute(students, internships, store=True):
    if not students or not internships:
        return {}
    results = score_matrix([student_doc(s) for s in students], [internship_doc(i) for i in internships],
                           get_weights())
    if store:
        _store(results)
    return results


def match_for(profile, internship, store=True):
    return compute([profile], [internship], store)[(profile.id, internship.id)]


def recommendations(profile, limit=None, include_ineligible=False):
    """Rank open internships for one student. Returns list of (internship, result)."""
    internships = [i for i in Internship.query.filter_by(status=InternshipStatus.PUBLISHED).all() if i.is_open]
    results = compute([profile], internships)
    ranked = sorted(((i, results[(profile.id, i.id)]) for i in internships),
                    key=lambda t: (not t[1]["eligible"], -t[1]["total"], t[0].id))
    if not include_ineligible:
        ranked = [t for t in ranked if t[1]["eligible"]]
    return ranked[:limit] if limit else ranked


def rank_applicants(internship, statuses=None):
    """Rank applicants of an internship: eligible first, then score desc, then CGPA, then earliest application."""
    q = Application.query.filter_by(internship_id=internship.id)
    if statuses:
        q = q.filter(Application.status.in_(statuses))
    apps = q.all()
    if not apps:
        return []
    results = compute([a.student for a in apps], [internship])
    rows = [(a, results[(a.student_id, internship.id)]) for a in apps]
    rows.sort(key=lambda t: (not t[1]["eligible"], -t[1]["total"], -(t[0].student.cgpa or 0),
                             t[0].created_at, t[0].student_id))
    return rows


def refresh_all():
    """Recompute and cache scores for every application (used after weight changes)."""
    apps = Application.query.all()
    by_internship = {}
    for a in apps:
        by_internship.setdefault(a.internship_id, []).append(a)
    for iid, group in by_internship.items():
        compute([a.student for a in group], [group[0].internship])
    return len(apps)
