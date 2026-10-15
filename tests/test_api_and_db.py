import os

from flask_migrate import upgrade
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db as _db
from app.models import Application
from tests.conftest import PASSWORD, login, make_admin, make_company, make_internship, make_student


def test_health_and_csrf_endpoints(client, app):
    assert client.get("/api/health").get_json() == {"status": "ok", "database": "ok"}
    assert "csrf_token" in client.get("/api/csrf-token").get_json()


def test_api_errors_are_json(client, app):
    make_student()
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.is_json
    client.post("/api/auth/login", json={"email": "s@test.local", "password": PASSWORD})
    r = client.post("/api/applications", data="not json", content_type="text/plain")
    assert r.status_code == 400 and "internship_id" in r.get_json()["error"]
    r = client.post("/api/applications", json={"internship_id": 9999})
    assert r.status_code == 404
    r = client.get("/api/match/9999")
    assert r.status_code == 404


def test_api_login_and_bad_credentials(client, app):
    make_student()
    assert client.post("/api/auth/login", json={"email": "s@test.local", "password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "s@test.local", "password": PASSWORD})
    assert r.status_code == 200 and r.get_json()["user"]["role"] == "student"
    assert client.get("/api/me").get_json()["profile"]["skills"] == []


def test_api_student_flow(client, app):
    c = make_company()
    i = make_internship(c, required=("Python",))
    make_internship(c, "Hidden draft", status="draft")
    make_student(skills=["Python"])
    login(client, "s@test.local")
    items = client.get("/api/internships").get_json()["items"]
    assert [x["id"] for x in items] == [i.id] and "match_score" in items[0]
    recs = client.get("/api/recommendations").get_json()
    assert recs["items"][0]["internship"]["id"] == i.id and "disclaimer" in recs
    r = client.post("/api/applications", json={"internship_id": i.id, "preference_rank": 1})
    assert r.status_code == 201 and r.get_json()["application"]["status"] == "submitted"
    assert len(client.get("/api/applications").get_json()["items"]) == 1
    assert client.get("/api/stats/student").status_code == 200


def test_api_admin_and_company_endpoints(client, app):
    make_admin()
    c = make_company(email="co@test.local")
    i = make_internship(c)
    login(client, "admin@test.local")
    for url in ["/api/stats/admin", f"/api/internships/{i.id}/rankings", "/api/allocation/runs", "/api/internships"]:
        assert client.get(url).status_code == 200, url
    r = client.post("/api/allocation/preview")
    assert r.status_code == 201
    run_id = r.get_json()["run_id"]
    assert client.post(f"/api/allocation/runs/{run_id}/discard").get_json()["status"] == "discarded"
    assert client.post(f"/api/allocation/runs/{run_id}/confirm").status_code == 409
    client.post("/api/auth/logout")
    login(client, "co@test.local")
    assert client.get("/api/stats/company").status_code == 200


def test_csrf_enforced_when_enabled(tmp_path):
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        _db.create_all()
        c = app.test_client()
        r = c.post("/login", data={"email": "a@b.c", "password": "x"})
        assert r.status_code == 302  # CSRF failure -> redirected with a flash message, no login attempt
        r = c.post("/api/notifications/read-all")
        assert r.status_code in (400, 401)
        _db.drop_all()


def test_unique_constraint_blocks_duplicate_application(app, db):
    c = make_company()
    i = make_internship(c)
    s = make_student()
    db.session.add(Application(student_id=s.id, internship_id=i.id))
    db.session.commit()
    db.session.add(Application(student_id=s.id, internship_id=i.id))
    try:
        db.session.commit()
        raise AssertionError("duplicate committed")
    except IntegrityError:
        db.session.rollback()


def test_cascade_delete_student(app, db):
    c = make_company()
    i = make_internship(c)
    s = make_student()
    db.session.add(Application(student_id=s.id, internship_id=i.id))
    db.session.commit()
    db.session.delete(s.user)
    db.session.commit()
    assert Application.query.count() == 0


def test_migrations_create_schema(tmp_path, monkeypatch):
    """Apply the Alembic migrations to a brand-new SQLite file and check every table exists."""
    import config
    db_file = tmp_path / "migrated.db"
    monkeypatch.setattr(config.TestingConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + str(db_file))
    app = create_app("testing")
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
    with app.app_context():
        assert str(_db.engine.url).endswith("migrated.db")
        upgrade(directory=migrations_dir)
        tables = set(inspect(_db.engine).get_table_names())
        _db.engine.dispose()
    expected = {"users", "student_profiles", "company_profiles", "internships", "internship_skills", "skills",
                "student_skills", "resumes", "applications", "match_scores", "allocation_runs", "allocations",
                "notifications", "feedback", "audit_logs", "announcements", "settings", "alembic_version"}
    assert expected <= tables


def test_seed_and_all_pages_render(app, client):
    """Seed sample data in the test DB and request every page for every role."""
    from app.cli import DEMO_PASSWORDS, seed
    seed()
    pages = {
        ("admin@demo.local", DEMO_PASSWORDS["admin"]): [
            "/admin/dashboard", "/admin/students", "/admin/students/1", "/admin/companies", "/admin/companies/new",
            "/admin/companies/1/edit", "/admin/internships", "/admin/internships/new", "/admin/internships/1/edit",
            "/admin/internships/1/applicants", "/admin/applications", "/admin/applications/1", "/admin/allocation",
            "/admin/reports", "/admin/reports/students.csv", "/admin/reports/internships.csv",
            "/admin/reports/applications.csv", "/admin/reports/allocations.csv", "/admin/feedback",
            "/admin/announcements", "/admin/settings", "/admin/audit", "/notifications", "/resume/1"],
        ("company1@demo.local", DEMO_PASSWORDS["company"]): [
            "/company/dashboard", "/company/profile", "/company/internships", "/company/internships/new",
            "/company/internships/1/edit", "/company/internships/1/applicants", "/company/allocations"],
        ("student1@demo.local", DEMO_PASSWORDS["student"]): [
            "/student/dashboard", "/student/profile", "/student/internships", "/student/internships?sort=stipend&paid=1",
            "/student/internships/1", "/student/applications", "/student/recommendations",
            "/student/recommendations?all=1", "/student/allocations", "/notifications", "/resume/1"],
    }
    for (email, pw), urls in pages.items():
        client.post("/logout")
        assert login(client, email, pw).status_code == 302
        for url in urls:
            r = client.get(url)
            assert r.status_code == 200, (email, url, r.status_code)
            r.close()
