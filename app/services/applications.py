"""Application workflow shared by HTML routes and the REST API."""
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Application, AppStatus, Role
from app.services import match_service
from app.services.audit import log_action
from app.services.notifications import notify


class ApplicationError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def apply(profile, internship, preference_rank=None, cover_note=""):
    if internship is None:
        raise ApplicationError("Internship not found.", 404)
    if not internship.is_open:
        raise ApplicationError("This internship is not accepting applications.", 400)
    if Application.query.filter_by(student_id=profile.id, internship_id=internship.id).first():
        raise ApplicationError("You have already applied to this internship.", 409)
    result = match_service.match_for(profile, internship)
    if not result["eligible"]:
        raise ApplicationError("You do not meet the eligibility criteria: " + " ".join(result["eligibility_reasons"]),
                               400)
    if preference_rank is None:
        preference_rank = Application.query.filter_by(student_id=profile.id).count() + 1
    try:
        preference_rank = max(1, min(50, int(preference_rank)))
    except (TypeError, ValueError):
        raise ApplicationError("Preference rank must be a number between 1 and 50.", 400)
    app_ = Application(student_id=profile.id, internship_id=internship.id, preference_rank=preference_rank,
                       cover_note=(cover_note or "").strip()[:2000] or None)
    db.session.add(app_)
    try:
        db.session.flush()
    except IntegrityError:  # race: duplicate insert
        db.session.rollback()
        raise ApplicationError("You have already applied to this internship.", 409)
    notify(profile.user, "Application submitted",
           f"Your application for {internship.title} at {internship.company.company_name} was submitted "
           f"(match score {result['total']:g}).", "application", "/student/applications")
    notify(internship.company.user, "New application",
           f"{profile.user.name} applied to {internship.title}.", "application",
           f"/company/internships/{internship.id}/applicants")
    db.session.commit()
    return app_, result


def update_status(app_, new_status, actor, note=""):
    """Change an application status according to the actor's allowed transitions."""
    if new_status not in AppStatus.ALL or new_status == AppStatus.ALLOCATED:
        raise ApplicationError("Invalid status. 'allocated' can only be set by the allocation process.")
    if actor.role == Role.COMPANY:
        if not actor.company_profile or app_.internship.company_id != actor.company_profile.id:
            raise ApplicationError("You can only review applications to your own internships.", 403)
        allowed = AppStatus.COMPANY_TRANSITIONS.get(app_.status, set())
    elif actor.role == Role.ADMIN:
        allowed = AppStatus.ADMIN_TRANSITIONS.get(app_.status, set())
    else:
        raise ApplicationError("You do not have permission for this action.", 403)
    if new_status == app_.status:
        return app_
    if new_status not in allowed:
        raise ApplicationError(f"Cannot change status from {app_.status} to {new_status}.", 409)
    old = app_.status
    app_.status = new_status
    if note:
        app_.reviewer_note = note.strip()[:255]
    messages = {
        AppStatus.SHORTLISTED: "Good news! You have been shortlisted for",
        AppStatus.SELECTED: "Congratulations! You have been selected by the company for",
        AppStatus.REJECTED: "Your application was not taken forward for",
        AppStatus.SUBMITTED: "Your application has been re-opened for",
    }
    if new_status in messages:
        notify(app_.student.user, f"Application {new_status}",
               f"{messages[new_status]} {app_.internship.title} at {app_.internship.company.company_name}."
               + (f" Note: {app_.reviewer_note}" if note else ""), "application", "/student/applications")
    log_action("application.status", "application", app_.id, f"{old} -> {new_status}", user=actor)
    db.session.commit()
    return app_


def withdraw(app_, profile):
    if app_.student_id != profile.id:
        raise ApplicationError("Not your application.", 403)
    if app_.status not in AppStatus.POOL:
        raise ApplicationError("Only pending applications can be withdrawn.", 409)
    app_.status = AppStatus.WITHDRAWN
    notify(app_.internship.company.user, "Application withdrawn",
           f"{profile.user.name} withdrew from {app_.internship.title}.", "application")
    db.session.commit()
