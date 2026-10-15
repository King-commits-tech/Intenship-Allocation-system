from app.extensions import db
from app.models.user import utcnow


class Skill(db.Model):
    """Canonical skill names (normalised via the skill dictionary)."""
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    category = db.Column(db.String(60), nullable=True)

    def __repr__(self):
        return f"<Skill {self.name}>"


class StudentSkill(db.Model):
    __tablename__ = "student_skills"
    __table_args__ = (db.UniqueConstraint("student_id", "skill_id", name="uq_student_skill"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    # manual | resume (resume = extracted, then confirmed by the student)
    source = db.Column(db.String(20), nullable=False, default="manual")

    skill = db.relationship("Skill")
    student = db.relationship("StudentProfile", back_populates="skill_links")


class StudentProfile(db.Model):
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    roll_number = db.Column(db.String(40), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    degree = db.Column(db.String(80), nullable=True)
    department = db.Column(db.String(80), nullable=True, index=True)
    year_of_study = db.Column(db.Integer, nullable=True)
    graduation_year = db.Column(db.Integer, nullable=True)
    cgpa = db.Column(db.Float, nullable=True)            # 0-10 scale
    percentage = db.Column(db.Float, nullable=True)      # 0-100, optional
    interests = db.Column(db.Text, nullable=True)
    projects = db.Column(db.Text, nullable=True)
    experience = db.Column(db.Text, nullable=True)
    certifications = db.Column(db.Text, nullable=True)
    preferred_domain = db.Column(db.String(80), nullable=True)
    preferred_location = db.Column(db.String(80), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="student_profile")
    skill_links = db.relationship("StudentSkill", back_populates="student", cascade="all, delete-orphan")
    resume = db.relationship("Resume", back_populates="student", uselist=False, cascade="all, delete-orphan")
    applications = db.relationship("Application", back_populates="student", cascade="all, delete-orphan")

    @property
    def skill_names(self):
        return sorted(link.skill.name for link in self.skill_links)

    COMPLETION_FIELDS = ("degree", "department", "year_of_study", "cgpa", "interests", "projects",
                         "preferred_domain", "phone")

    def completion_percent(self):
        filled = sum(1 for f in self.COMPLETION_FIELDS if getattr(self, f) not in (None, ""))
        total = len(self.COMPLETION_FIELDS) + 2
        filled += 1 if self.skill_links else 0
        filled += 1 if self.resume else 0
        return int(round(100 * filled / total))

    def missing_fields(self):
        labels = {"degree": "Degree", "department": "Department", "year_of_study": "Year of study",
                  "cgpa": "CGPA", "interests": "Interests", "projects": "Projects",
                  "preferred_domain": "Preferred domain", "phone": "Phone"}
        missing = [labels[f] for f in self.COMPLETION_FIELDS if getattr(self, f) in (None, "")]
        if not self.skill_links:
            missing.append("Skills")
        if not self.resume:
            missing.append("Resume")
        return missing

    def to_dict(self):
        return {
            "id": self.id, "name": self.user.name, "email": self.user.email,
            "roll_number": self.roll_number, "degree": self.degree, "department": self.department,
            "year_of_study": self.year_of_study, "cgpa": self.cgpa, "skills": self.skill_names,
            "interests": self.interests, "preferred_domain": self.preferred_domain,
            "profile_completion": self.completion_percent(),
        }


class CompanyProfile(db.Model):
    __tablename__ = "company_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_name = db.Column(db.String(150), nullable=False, index=True)
    industry = db.Column(db.String(80), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    contact_person = db.Column(db.String(120), nullable=True)
    # Companies self-register but must be verified by a college admin before publishing.
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="company_profile")
    internships = db.relationship("Internship", back_populates="company", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "company_name": self.company_name, "industry": self.industry,
                "website": self.website, "location": self.location, "is_verified": self.is_verified}


class Resume(db.Model):
    """Resume metadata; the PDF itself lives in UPLOAD_FOLDER under a random name."""
    __tablename__ = "resumes"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
                           unique=True, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(64), unique=True, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    extracted_text = db.Column(db.Text, nullable=True)
    extracted_skills = db.Column(db.Text, nullable=True)  # comma separated canonical names
    # ok | no_text (scanned/image PDF) | error
    extraction_status = db.Column(db.String(20), nullable=False, default="ok")
    extraction_message = db.Column(db.String(255), nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    student = db.relationship("StudentProfile", back_populates="resume")

    @property
    def extracted_skill_list(self):
        return [s for s in (self.extracted_skills or "").split(",") if s]
