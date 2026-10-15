"""Server-side parsing/validation of the larger forms shared by several blueprints."""
from app.extensions import db
from app.models import (DOMAINS, WORK_MODES, AppStatus, Application, InternshipSkill, InternshipStatus,
                        StudentSkill)
from app.services.notifications import notify
from app.services.skills import get_or_create_skill, parse_skill_list
from app.utils.validators import FormErrors, clean_str, opt_date, opt_float, opt_int


def parse_internship_form(form):
    errors = FormErrors()
    data = {
        "title": clean_str(form.get("title"), 150),
        "description": clean_str(form.get("description"), 10000),
        "domain": clean_str(form.get("domain"), 80),
        "location": clean_str(form.get("location"), 120),
        "work_mode": clean_str(form.get("work_mode"), 20) or "On-site",
        "duration_weeks": opt_int(form.get("duration_weeks"), "Duration (weeks)", errors, 1, 104),
        "stipend": opt_int(form.get("stipend"), "Stipend", errors, 0, 1_000_000),
        "seats": opt_int(form.get("seats"), "Seats", errors, 1, 500),
        "min_cgpa": opt_float(form.get("min_cgpa"), "Minimum CGPA", errors, 0, 10),
        "eligible_departments": clean_str(form.get("eligible_departments"), 255) or None,
        "eligible_years": clean_str(form.get("eligible_years"), 40) or None,
        "deadline": opt_date(form.get("deadline"), "Deadline", errors),
        "required_skills": parse_skill_list(form.get("required_skills")),
        "preferred_skills": parse_skill_list(form.get("preferred_skills")),
    }
    if len(data["title"]) < 3:
        errors.add("Title must be at least 3 characters.")
    if len(data["description"]) < 20:
        errors.add("Description must be at least 20 characters.")
    if data["domain"] not in DOMAINS:
        errors.add("Please choose a valid domain.")
    if data["work_mode"] not in WORK_MODES:
        errors.add("Please choose a valid work mode.")
    if data["seats"] is None and not any("Seats" in e for e in errors):
        errors.add("Seats is required.")
    if data["duration_weeks"] is None and not any("Duration" in e for e in errors):
        data["duration_weeks"] = 8
    if data["eligible_years"]:
        parts = [p.strip() for p in data["eligible_years"].split(",") if p.strip()]
        if not all(p.isdigit() and 1 <= int(p) <= 6 for p in parts):
            errors.add("Eligible years must be comma separated numbers between 1 and 6, e.g. 3,4.")
        data["eligible_years"] = ",".join(parts) or None
    if data["eligible_departments"]:
        parts = [p.strip() for p in data["eligible_departments"].split(",") if p.strip()]
        data["eligible_departments"] = ", ".join(parts) or None
    if not data["required_skills"] and not data["preferred_skills"]:
        errors.add("Add at least one required or preferred skill so matching is meaningful.")
    pref_lower = {s.lower() for s in data["required_skills"]}
    data["preferred_skills"] = [s for s in data["preferred_skills"] if s.lower() not in pref_lower]
    return data, errors


def apply_internship(internship, data):
    for key in ("title", "description", "domain", "location", "work_mode", "duration_weeks", "stipend", "seats",
                "min_cgpa", "eligible_departments", "eligible_years", "deadline"):
        setattr(internship, key, data[key])
    internship.skill_links.clear()
    db.session.flush()
    for name in data["required_skills"]:
        internship.skill_links.append(InternshipSkill(skill=get_or_create_skill(name), is_required=True))
    for name in data["preferred_skills"]:
        internship.skill_links.append(InternshipSkill(skill=get_or_create_skill(name), is_required=False))


def notify_internship_update(internship):
    """Tell applicants that a published internship they applied to changed."""
    if internship.status != InternshipStatus.PUBLISHED:
        return 0
    apps = Application.query.filter(Application.internship_id == internship.id,
                                    Application.status.notin_([AppStatus.WITHDRAWN, AppStatus.REJECTED])).all()
    for a in apps:
        notify(a.student.user, "Internship updated",
               f"Details of {internship.title} ({internship.company.company_name}) were updated.",
               "internship", f"/student/internships/{internship.id}")
    return len(apps)


def set_student_skills(profile, names, source="manual"):
    """Replace a student's skill list with the given canonical names."""
    names = parse_skill_list(",".join(names))
    existing = {l.skill.name.lower(): l for l in profile.skill_links}
    wanted = {n.lower() for n in names}
    for key, link in list(existing.items()):
        if key not in wanted:
            profile.skill_links.remove(link)
    for n in names:
        if n.lower() not in existing:
            profile.skill_links.append(StudentSkill(skill=get_or_create_skill(n), source=source))


def add_student_skills(profile, names, source="resume"):
    existing = {l.skill.name.lower() for l in profile.skill_links}
    added = []
    for n in parse_skill_list(",".join(names)):
        if n.lower() not in existing:
            profile.skill_links.append(StudentSkill(skill=get_or_create_skill(n), source=source))
            existing.add(n.lower())
            added.append(n)
    return added
