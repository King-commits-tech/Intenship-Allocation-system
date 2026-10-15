from app.models import (Application, AppStatus, Internship, InternshipStatus, Notification, Role, User)
from tests.conftest import login, make_admin, make_company, make_internship, make_student

FORM = {"title": "Data Intern", "description": "Analyse data with Python and SQL for dashboards.",
        "domain": "Data Science", "work_mode": "Remote", "seats": "2", "duration_weeks": "8",
        "required_skills": "python, sql", "preferred_skills": "Power BI, SQL", "min_cgpa": "7"}


def test_company_creates_internship_draft_until_verified(client, app):
    make_company(email="u@test.local", verified=False)
    login(client, "u@test.local")
    r = client.post("/company/internships/new", data={**FORM, "publish": "1"})
    assert r.status_code == 302
    i = Internship.query.one()
    assert i.status == InternshipStatus.DRAFT
    assert i.required_skills == ["Python", "SQL"]
    assert i.preferred_skills == ["Power BI"]  # duplicate of a required skill removed
    r = client.post(f"/company/internships/{i.id}/status", data={"status": "published"})
    assert Internship.query.one().status == InternshipStatus.DRAFT


def test_verified_company_publishes_and_edits(client, app, db):
    make_company(email="v@test.local")
    login(client, "v@test.local")
    client.post("/company/internships/new", data={**FORM, "publish": "1"})
    i = Internship.query.one()
    assert i.status == InternshipStatus.PUBLISHED and i.min_cgpa == 7.0
    s = make_student(skills=["Python", "SQL"], cgpa=8)
    db.session.add(Application(student_id=s.id, internship_id=i.id))
    db.session.commit()
    r = client.post(f"/company/internships/{i.id}/edit", data={**FORM, "title": "Data Analyst Intern", "seats": "3"})
    assert r.status_code == 302
    db.session.refresh(i)
    assert i.title == "Data Analyst Intern" and i.seats == 3
    assert Notification.query.filter_by(user_id=s.user_id, category="internship").count() == 1


def test_internship_validation(client, app):
    make_company(email="w@test.local")
    login(client, "w@test.local")
    r = client.post("/company/internships/new", data={**FORM, "title": "", "seats": "0", "domain": "Nope",
                                                      "required_skills": "", "preferred_skills": "",
                                                      "eligible_years": "abc"})
    assert r.status_code == 400
    assert Internship.query.count() == 0


def test_admin_creates_internship_for_company(client, app):
    c = make_company()
    make_admin()
    login(client, "admin@test.local")
    r = client.post("/admin/internships/new", data={**FORM, "company_id": str(c.id), "publish": "1"})
    assert r.status_code == 302
    assert Internship.query.one().company_id == c.id


def test_student_applies_and_notifications_created(client, app):
    c = make_company()
    i = make_internship(c, required=("Python",))
    s = make_student(skills=["Python"])
    login(client, "s@test.local")
    r = client.post(f"/student/internships/{i.id}/apply", data={"preference_rank": "1", "cover_note": "Hi"})
    assert r.status_code == 302
    a = Application.query.one()
    assert a.status == AppStatus.SUBMITTED and a.preference_rank == 1
    assert Notification.query.filter_by(user_id=s.user_id, title="Application submitted").count() == 1
    assert Notification.query.filter_by(user_id=c.user_id, title="New application").count() == 1


def test_duplicate_application_prevented(client, app):
    c = make_company()
    i = make_internship(c)
    make_student(skills=["Python"])
    login(client, "s@test.local")
    client.post(f"/student/internships/{i.id}/apply", data={"preference_rank": "1"})
    client.post(f"/student/internships/{i.id}/apply", data={"preference_rank": "2"})
    assert Application.query.count() == 1
    r = client.post("/api/applications", json={"internship_id": i.id})
    assert r.status_code == 409 and "already applied" in r.get_json()["error"]


def test_ineligible_or_closed_cannot_apply(client, app, db):
    c = make_company()
    strict = make_internship(c, "Strict", min_cgpa=9.0)
    closed = make_internship(c, "Closed", status=InternshipStatus.CLOSED)
    expired = make_internship(c, "Expired", deadline_days=-1)
    make_student(cgpa=7.0)
    login(client, "s@test.local")
    for i in (strict, closed, expired):
        client.post(f"/student/internships/{i.id}/apply", data={"preference_rank": "1"})
    assert Application.query.count() == 0
    r = client.post("/api/applications", json={"internship_id": strict.id})
    assert r.status_code == 400 and "eligibility" in r.get_json()["error"]


def test_company_status_transitions(client, app, db):
    c = make_company(email="co@test.local")
    i = make_internship(c)
    s = make_student()
    a = Application(student_id=s.id, internship_id=i.id)
    db.session.add(a)
    db.session.commit()
    login(client, "co@test.local")
    # invalid jump: submitted -> selected not allowed for companies
    client.post(f"/company/applications/{a.id}/status", data={"status": "selected"})
    assert db.session.get(Application, a.id).status == AppStatus.SUBMITTED
    client.post(f"/company/applications/{a.id}/status", data={"status": "shortlisted", "note": "Great profile"})
    assert db.session.get(Application, a.id).status == AppStatus.SHORTLISTED
    r = client.patch(f"/api/applications/{a.id}/status", json={"status": "selected"})
    assert r.status_code == 200 and r.get_json()["application"]["status"] == "selected"
    r = client.patch(f"/api/applications/{a.id}/status", json={"status": "allocated"})
    assert r.status_code == 400  # only the allocation engine may allocate
    titles = [n.title for n in Notification.query.filter_by(user_id=s.user_id).all()]
    assert "Application shortlisted" in titles and "Application selected" in titles


def test_student_withdraw_and_preference(client, app, db):
    c = make_company()
    i = make_internship(c)
    s = make_student()
    a = Application(student_id=s.id, internship_id=i.id, preference_rank=3)
    db.session.add(a)
    db.session.commit()
    login(client, "s@test.local")
    client.post(f"/student/applications/{a.id}/preference", data={"preference_rank": "1"})
    assert db.session.get(Application, a.id).preference_rank == 1
    client.post(f"/student/applications/{a.id}/withdraw")
    assert db.session.get(Application, a.id).status == AppStatus.WITHDRAWN


def test_notifications_mark_read(client, app):
    from app.services.notifications import notify
    from app.extensions import db
    s = make_student()
    n = notify(s.user, "Hello", "World")
    notify(s.user, "Second", "Msg")
    db.session.commit()
    login(client, "s@test.local")
    assert client.get("/api/notifications?unread=1").get_json()["unread"] == 2
    r = client.post(f"/api/notifications/{n.id}/read")
    assert r.get_json()["unread"] == 1
    client.post("/notifications/read-all")
    assert User.query.filter_by(role=Role.STUDENT).one().unread_count() == 0


def test_announcement_notifies_audience(client, app):
    make_admin()
    make_student(email="s1@test.local")
    make_company(email="c1@test.local")
    login(client, "admin@test.local")
    client.post("/admin/announcements", data={"title": "Drive", "body": "Placement drive on Monday",
                                              "audience": "student"})
    assert Notification.query.filter_by(category="announcement").count() == 1


def test_feedback_only_for_allocated(client, app, db):
    from app.models import Allocation, AllocationStatus, Feedback
    c = make_company()
    i = make_internship(c)
    s = make_student()
    login(client, "s@test.local")
    client.post(f"/student/feedback/{i.id}", data={"rating": "5"})
    assert Feedback.query.count() == 0
    db.session.add(Allocation(student_id=s.id, internship_id=i.id, status=AllocationStatus.ACTIVE, score=80))
    db.session.commit()
    client.post(f"/student/feedback/{i.id}", data={"rating": "4", "learning_rating": "5", "comments": "Good"})
    fb = Feedback.query.one()
    assert fb.rating == 4 and fb.learning_rating == 5
