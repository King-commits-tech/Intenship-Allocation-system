from app.models import Application, AppStatus
from tests.conftest import login, make_admin, make_company, make_internship, make_student


def test_unauthenticated_redirects_and_api_401(client, app):
    assert client.get("/admin/dashboard").status_code == 302
    r = client.get("/api/recommendations")
    assert r.status_code == 401 and r.is_json


def test_student_cannot_access_admin_or_company(client, app):
    make_student(email="s@test.local")
    login(client, "s@test.local")
    for url in ["/admin/dashboard", "/admin/students", "/admin/allocation", "/company/dashboard"]:
        assert client.get(url).status_code == 403, url
    assert client.post("/admin/allocation/preview").status_code == 403
    r = client.post("/api/allocation/preview")
    assert r.status_code == 403 and r.is_json


def test_company_cannot_access_admin_or_student(client, app):
    make_company(email="c@test.local")
    login(client, "c@test.local")
    assert client.get("/admin/settings").status_code == 403
    assert client.get("/student/profile").status_code == 403


def test_company_cannot_touch_other_companies_data(client, app, db):
    mine = make_company(email="mine@test.local", name="Mine")
    other = make_company(email="other@test.local", name="Other")
    s = make_student(skills=["Python", "SQL"])
    theirs = make_internship(other)
    a = Application(student_id=s.id, internship_id=theirs.id)
    db.session.add(a)
    db.session.commit()
    login(client, "mine@test.local")
    assert client.get(f"/company/internships/{theirs.id}/edit").status_code == 403
    assert client.get(f"/company/internships/{theirs.id}/applicants").status_code == 403
    assert client.get(f"/company/applications/{a.id}").status_code == 403
    assert client.post(f"/company/applications/{a.id}/status", data={"status": "shortlisted"}).status_code == 403
    r = client.patch(f"/api/applications/{a.id}/status", json={"status": "shortlisted"})
    assert r.status_code == 404
    assert db.session.get(Application, a.id).status == AppStatus.SUBMITTED
    assert mine  # unused helper reference


def test_student_cannot_view_other_students_resume(client, app, db):
    from app.models import Resume
    s1 = make_student(email="s1@test.local")
    s2 = make_student(email="s2@test.local")
    db.session.add(Resume(student_id=s2.id, original_filename="x.pdf", stored_filename="a" * 32 + ".pdf",
                          size_bytes=10))
    db.session.commit()
    login(client, "s1@test.local")
    assert client.get(f"/resume/{s2.id}").status_code == 403
    assert s1


def test_admin_can_access_everything(client, app):
    make_admin()
    login(client, "admin@test.local")
    for url in ["/admin/dashboard", "/admin/students", "/admin/companies", "/admin/internships",
                "/admin/applications", "/admin/allocation", "/admin/settings", "/admin/audit", "/admin/reports",
                "/admin/feedback", "/admin/announcements"]:
        assert client.get(url).status_code == 200, url
