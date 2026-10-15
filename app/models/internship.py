from datetime import date

from app.extensions import db
from app.models.user import utcnow


class InternshipStatus:
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"
    ALL = (DRAFT, PUBLISHED, CLOSED)


DOMAINS = [
    "Web Development", "Data Science", "Machine Learning", "Mobile Development", "Cloud & DevOps",
    "Cybersecurity", "UI/UX Design", "Embedded Systems", "Software Testing", "Business Analytics",
    "Digital Marketing", "Other",
]
WORK_MODES = ["On-site", "Remote", "Hybrid"]


class InternshipSkill(db.Model):
    """Required or preferred (optional) skill for an internship."""
    __tablename__ = "internship_skills"
    __table_args__ = (db.UniqueConstraint("internship_id", "skill_id", name="uq_internship_skill"),)

    id = db.Column(db.Integer, primary_key=True)
    internship_id = db.Column(db.Integer, db.ForeignKey("internships.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    is_required = db.Column(db.Boolean, nullable=False, default=True)

    skill = db.relationship("Skill")
    internship = db.relationship("Internship", back_populates="skill_links")


class Internship(db.Model):
    __tablename__ = "internships"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company_profiles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    domain = db.Column(db.String(80), nullable=False, index=True)
    location = db.Column(db.String(120), nullable=True)
    work_mode = db.Column(db.String(20), nullable=False, default="On-site")
    duration_weeks = db.Column(db.Integer, nullable=False, default=8)
    stipend = db.Column(db.Integer, nullable=True)  # per month, INR
    seats = db.Column(db.Integer, nullable=False, default=1)
    # Hard eligibility rules - only enforced when set.
    min_cgpa = db.Column(db.Float, nullable=True)
    eligible_departments = db.Column(db.String(255), nullable=True)  # comma separated, blank = all
    eligible_years = db.Column(db.String(40), nullable=True)         # e.g. "3,4", blank = all
    deadline = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=InternshipStatus.DRAFT, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    company = db.relationship("CompanyProfile", back_populates="internships")
    skill_links = db.relationship("InternshipSkill", back_populates="internship", cascade="all, delete-orphan")
    applications = db.relationship("Application", back_populates="internship", cascade="all, delete-orphan")

    @property
    def required_skills(self):
        return sorted(l.skill.name for l in self.skill_links if l.is_required)

    @property
    def preferred_skills(self):
        return sorted(l.skill.name for l in self.skill_links if not l.is_required)

    @property
    def department_list(self):
        return [d.strip() for d in (self.eligible_departments or "").split(",") if d.strip()]

    @property
    def year_list(self):
        out = []
        for y in (self.eligible_years or "").split(","):
            y = y.strip()
            if y.isdigit():
                out.append(int(y))
        return out

    @property
    def is_open(self):
        if self.status != InternshipStatus.PUBLISHED:
            return False
        return self.deadline is None or self.deadline >= date.today()

    def active_allocation_count(self):
        from app.models.application import Allocation, AllocationStatus
        return Allocation.query.filter_by(internship_id=self.id, status=AllocationStatus.ACTIVE).count()

    def seats_left(self):
        return max(0, self.seats - self.active_allocation_count())

    def to_dict(self, include_description=True):
        data = {
            "id": self.id, "title": self.title, "company": self.company.company_name,
            "company_id": self.company_id, "domain": self.domain, "location": self.location,
            "work_mode": self.work_mode, "duration_weeks": self.duration_weeks, "stipend": self.stipend,
            "seats": self.seats, "seats_left": self.seats_left(), "min_cgpa": self.min_cgpa,
            "eligible_departments": self.department_list, "eligible_years": self.year_list,
            "deadline": self.deadline.isoformat() if self.deadline else None, "status": self.status,
            "required_skills": self.required_skills, "preferred_skills": self.preferred_skills,
            "is_open": self.is_open,
        }
        if include_description:
            data["description"] = self.description
        return data
