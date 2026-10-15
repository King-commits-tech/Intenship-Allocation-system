"""Test fixtures. Tests use an isolated in-memory SQLite database and a temporary upload
folder, so they never touch real user data."""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import (CompanyProfile, Internship, InternshipStatus, Role, StudentProfile,  # noqa: E402
                        User)
from app.services.forms import apply_internship, set_student_skills  # noqa: E402

PASSWORD = "Passw0rd!"


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


def make_user(role, email, name="Test User", password=PASSWORD, active=True):
    u = User(email=email, name=name, role=role, is_active_flag=active)
    u.set_password(password)
    _db.session.add(u)
    _db.session.flush()
    return u


def make_student(email="s@test.local", name="Student One", skills=(), cgpa=8.0, department="Computer Science",
                 year=3, domain=None, interests=None, projects=None):
    u = make_user(Role.STUDENT, email, name)
    p = StudentProfile(user_id=u.id, cgpa=cgpa, department=department, year_of_study=year,
                       preferred_domain=domain, interests=interests, projects=projects)
    _db.session.add(p)
    _db.session.flush()
    set_student_skills(p, list(skills))
    _db.session.commit()
    return p


def make_company(email="c@test.local", name="Acme Corp", verified=True):
    u = make_user(Role.COMPANY, email, "HR " + name)
    c = CompanyProfile(user_id=u.id, company_name=name, is_verified=verified)
    _db.session.add(c)
    _db.session.commit()
    return c


def make_admin(email="admin@test.local"):
    u = make_user(Role.ADMIN, email, "Admin")
    _db.session.commit()
    return u


def make_internship(company, title="Python Developer Intern", required=("Python", "SQL"), preferred=(),
                    seats=1, min_cgpa=None, domain="Web Development", status=InternshipStatus.PUBLISHED,
                    departments=None, years=None, deadline_days=30):
    i = Internship(company_id=company.id, status=status)
    _db.session.add(i)
    apply_internship(i, {
        "title": title, "description": f"{title}: work on real projects using " + ", ".join(required),
        "domain": domain, "location": "Indore", "work_mode": "On-site", "duration_weeks": 8, "stipend": 10000,
        "seats": seats, "min_cgpa": min_cgpa, "eligible_departments": departments, "eligible_years": years,
        "deadline": date.today() + timedelta(days=deadline_days) if deadline_days is not None else None,
        "required_skills": list(required), "preferred_skills": list(preferred),
    })
    _db.session.commit()
    return i


def login(client, email, password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password})
