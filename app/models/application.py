import json

from app.extensions import db
from app.models.user import utcnow


class AppStatus:
    SUBMITTED = "submitted"
    SHORTLISTED = "shortlisted"
    SELECTED = "selected"
    REJECTED = "rejected"
    ALLOCATED = "allocated"
    WITHDRAWN = "withdrawn"
    ALL = (SUBMITTED, SHORTLISTED, SELECTED, REJECTED, ALLOCATED, WITHDRAWN)
    # statuses that still take part in allocation
    POOL = (SUBMITTED, SHORTLISTED, SELECTED)

    # Transitions a company reviewer may perform. "allocated" is set only by the allocation engine.
    COMPANY_TRANSITIONS = {
        SUBMITTED: {SHORTLISTED, REJECTED},
        SHORTLISTED: {SELECTED, REJECTED},
        SELECTED: {REJECTED, SHORTLISTED},
        REJECTED: set(),
        ALLOCATED: set(),
        WITHDRAWN: set(),
    }
    # Admins can additionally re-open rejected / withdrawn applications.
    ADMIN_TRANSITIONS = {
        SUBMITTED: {SHORTLISTED, REJECTED, SELECTED},
        SHORTLISTED: {SUBMITTED, SELECTED, REJECTED},
        SELECTED: {SHORTLISTED, REJECTED},
        REJECTED: {SUBMITTED},
        WITHDRAWN: {SUBMITTED},
        ALLOCATED: set(),
    }


class Application(db.Model):
    __tablename__ = "applications"
    # One application per student per internship (prevents duplicates at DB level).
    __table_args__ = (db.UniqueConstraint("student_id", "internship_id", name="uq_application"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    internship_id = db.Column(db.Integer, db.ForeignKey("internships.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=AppStatus.SUBMITTED, index=True)
    preference_rank = db.Column(db.Integer, nullable=False, default=1)  # 1 = most preferred
    cover_note = db.Column(db.Text, nullable=True)
    reviewer_note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    student = db.relationship("StudentProfile", back_populates="applications")
    internship = db.relationship("Internship", back_populates="applications")

    def to_dict(self):
        return {
            "id": self.id, "student_id": self.student_id, "student_name": self.student.user.name,
            "internship_id": self.internship_id, "internship_title": self.internship.title,
            "company": self.internship.company.company_name, "status": self.status,
            "preference_rank": self.preference_rank, "cover_note": self.cover_note,
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
        }


class MatchScore(db.Model):
    """Cached, explainable match result for a (student, internship) pair."""
    __tablename__ = "match_scores"
    __table_args__ = (db.UniqueConstraint("student_id", "internship_id", name="uq_match"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    internship_id = db.Column(db.Integer, db.ForeignKey("internships.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    total_score = db.Column(db.Float, nullable=False, default=0)
    skill_score = db.Column(db.Float, nullable=False, default=0)
    project_score = db.Column(db.Float, nullable=False, default=0)
    interest_score = db.Column(db.Float, nullable=False, default=0)
    academic_score = db.Column(db.Float, nullable=False, default=0)
    is_eligible = db.Column(db.Boolean, nullable=False, default=True)
    explanation_json = db.Column(db.Text, nullable=True)
    computed_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def explanation(self):
        try:
            return json.loads(self.explanation_json or "{}")
        except ValueError:
            return {}


class RunStatus:
    PREVIEW = "preview"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    FAILED = "failed"


class AllocationRun(db.Model):
    __tablename__ = "allocation_runs"

    id = db.Column(db.Integer, primary_key=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=RunStatus.PREVIEW, index=True)
    policy = db.Column(db.String(60), nullable=False, default="student-proposing deferred acceptance")
    params_json = db.Column(db.Text, nullable=True)
    summary_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("User")
    allocations = db.relationship("Allocation", back_populates="run", cascade="all, delete-orphan")

    @property
    def summary(self):
        try:
            return json.loads(self.summary_json or "{}")
        except ValueError:
            return {}

    @property
    def params(self):
        try:
            return json.loads(self.params_json or "{}")
        except ValueError:
            return {}


class AllocationStatus:
    PROPOSED = "proposed"     # part of a preview run, not yet binding
    ACTIVE = "active"         # confirmed allocation
    CANCELLED = "cancelled"
    DISCARDED = "discarded"   # preview that was thrown away


class Allocation(db.Model):
    __tablename__ = "allocations"
    __table_args__ = (db.UniqueConstraint("run_id", "student_id", "internship_id", name="uq_run_alloc"),)

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("allocation_runs.id", ondelete="CASCADE"), nullable=True,
                       index=True)  # null = manual allocation by admin
    student_id = db.Column(db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    internship_id = db.Column(db.Integer, db.ForeignKey("internships.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)
    score = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=AllocationStatus.PROPOSED, index=True)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    run = db.relationship("AllocationRun", back_populates="allocations")
    student = db.relationship("StudentProfile")
    internship = db.relationship("Internship")
    application = db.relationship("Application")

    def to_dict(self):
        return {
            "id": self.id, "run_id": self.run_id, "student_id": self.student_id,
            "student_name": self.student.user.name, "internship_id": self.internship_id,
            "internship_title": self.internship.title, "company": self.internship.company.company_name,
            "score": self.score, "status": self.status, "note": self.note,
            "created_at": self.created_at.isoformat(),
        }
