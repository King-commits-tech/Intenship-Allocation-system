from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    """Naive UTC timestamp (portable across SQLite and MySQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role:
    STUDENT = "student"
    ADMIN = "admin"
    COMPANY = "company"
    ALL = (STUDENT, ADMIN, COMPANY)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    is_active_flag = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    student_profile = db.relationship("StudentProfile", back_populates="user", uselist=False,
                                      cascade="all, delete-orphan")
    company_profile = db.relationship("CompanyProfile", back_populates="user", uselist=False,
                                      cascade="all, delete-orphan")
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete-orphan",
                                    lazy="dynamic")

    # --- password handling -------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- flask-login -------------------------------------------------------
    @property
    def is_active(self):
        return bool(self.is_active_flag)

    def is_locked(self):
        return self.locked_until is not None and self.locked_until > utcnow()

    def register_failed_login(self, max_attempts, lock_minutes):
        self.failed_logins = (self.failed_logins or 0) + 1
        if self.failed_logins >= max_attempts:
            self.locked_until = utcnow() + timedelta(minutes=lock_minutes)
            self.failed_logins = 0

    def register_successful_login(self):
        self.failed_logins = 0
        self.locked_until = None
        self.last_login_at = utcnow()

    @property
    def is_student(self):
        return self.role == Role.STUDENT

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_company(self):
        return self.role == Role.COMPANY

    def unread_count(self):
        return self.notifications.filter_by(is_read=False).count()

    def to_dict(self):
        return {"id": self.id, "email": self.email, "name": self.name, "role": self.role,
                "is_active": self.is_active}

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
