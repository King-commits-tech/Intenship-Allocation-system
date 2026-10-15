import io
import os

import pytest

from app.models import StudentProfile
from app.services.resume import ResumeError, resolve_path
from app.utils.pdfgen import make_pdf
from tests.conftest import login, make_student


def _upload(client, data, name="resume.pdf"):
    return client.post("/student/resume", data={"resume": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_profile_create_and_validation(client, app, db):
    p = make_student(email="p@test.local", cgpa=None)
    login(client, "p@test.local")
    r = client.post("/student/profile", data={"name": "Pat", "cgpa": "11", "year_of_study": "3"})
    assert r.status_code == 400  # CGPA out of range
    r = client.post("/student/profile", data={
        "name": "Pat Kumar", "cgpa": "8.4", "year_of_study": "3", "department": "IT",
        "skills": "py, JS, machine learning, ReactJS", "interests": "web apps",
        "preferred_domain": "Web Development", "projects": "Built a React and Flask app"})
    assert r.status_code == 302
    db.session.refresh(p)
    assert p.cgpa == 8.4 and p.user.name == "Pat Kumar"
    # aliases normalised to canonical skills
    assert {"JavaScript", "Machine Learning", "React"} <= set(p.skill_names)
    assert 0 < p.completion_percent() < 100
    assert "Resume" in p.missing_fields()


def test_invalid_domain_rejected(client, app):
    make_student(email="d@test.local")
    login(client, "d@test.local")
    r = client.post("/student/profile", data={"name": "D", "preferred_domain": "Hacking<script>"})
    assert r.status_code == 400


def test_resume_upload_rejects_bad_files(client, app):
    make_student(email="r@test.local")
    login(client, "r@test.local")
    r = client.post("/student/resume", data={"resume": (io.BytesIO(b"hello"), "resume.txt")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Only PDF resumes are accepted" in r.data
    r = client.post("/student/resume", data={"resume": (io.BytesIO(b"MZ fake exe"), "resume.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"not a valid PDF" in r.data
    r = client.post("/student/resume", data={"resume": (io.BytesIO(b""), "resume.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"empty" in r.data
    assert StudentProfile.query.one().resume is None


def test_resume_too_large(client, app):
    make_student(email="big@test.local")
    login(client, "big@test.local")
    big = b"%PDF-" + b"0" * int(app.config["MAX_RESUME_MB"] * 1024 * 1024 + 10)
    r = _upload(client, big)
    assert r.status_code in (302, 413)
    assert StudentProfile.query.one().resume is None


def test_resume_extraction_adds_skills(client, app, db):
    p = make_student(email="x@test.local", skills=[])
    login(client, "x@test.local")
    pdf = make_pdf(["Jane Doe - Resume", "Skills: Python, Flask, ReactJS, MySQL and Docker",
                    "Built REST APIs and machine-learning models", "Comfortable to go anywhere"])
    r = _upload(client, pdf, "../../etc/passwd.pdf")
    assert r.status_code == 302
    db.session.refresh(p)
    res = p.resume
    assert res.extraction_status == "ok"
    assert res.original_filename == "etc_passwd.pdf"  # sanitised
    assert len(res.stored_filename) == 36 and res.stored_filename.endswith(".pdf")
    assert {"Python", "Flask", "React", "MySQL", "Docker", "REST API", "Machine Learning"} <= set(res.extracted_skill_list)
    assert "Go" not in res.extracted_skill_list  # lowercase "go" in prose is not the language
    assert {"Python", "Flask"} <= set(p.skill_names)
    path = resolve_path(res.stored_filename)
    assert os.path.exists(path) and path.startswith(app.config["UPLOAD_FOLDER"])
    # owner can view; file served as PDF
    r = client.get(f"/resume/{p.id}")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    r.close()


def test_scanned_pdf_handled_gracefully(client, app, db):
    p = make_student(email="scan@test.local", skills=["Python"])
    login(client, "scan@test.local")
    r = _upload(client, make_pdf([]))  # valid PDF without text = like a scanned image
    assert r.status_code == 302
    db.session.refresh(p)
    assert p.resume.extraction_status == "no_text"
    assert "OCR" in p.resume.extraction_message
    assert p.skill_names == ["Python"]


def test_corrupt_pdf_handled(client, app, db):
    p = make_student(email="bad@test.local")
    login(client, "bad@test.local")
    assert _upload(client, b"%PDF-1.4 this is not really a pdf").status_code == 302
    db.session.refresh(p)
    assert p.resume.extraction_status in ("error", "no_text")


def test_path_traversal_blocked(app):
    for bad in ["../secret.pdf", "/etc/passwd", "..", "", "a/b.pdf"]:
        with pytest.raises(ResumeError):
            resolve_path(bad)
