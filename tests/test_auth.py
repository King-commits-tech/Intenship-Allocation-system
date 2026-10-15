from app.models import CompanyProfile, Role, StudentProfile, User
from tests.conftest import PASSWORD, login, make_student, make_user


def test_password_is_hashed(app, db):
    u = make_user(Role.STUDENT, "hash@test.local")
    assert u.password_hash != PASSWORD
    assert u.password_hash.startswith(("scrypt:", "pbkdf2:"))
    assert u.check_password(PASSWORD)
    assert not u.check_password("wrong-password")


def test_register_student_creates_profile(client, app):
    r = client.post("/register", data={"role": "student", "name": "New Student", "email": "New@Test.local",
                                       "password": "abcd1234", "confirm_password": "abcd1234",
                                       "department": "IT"})
    assert r.status_code == 302
    u = User.query.filter_by(email="new@test.local").one()
    assert u.role == Role.STUDENT
    assert StudentProfile.query.filter_by(user_id=u.id).one().department == "IT"


def test_register_company_is_unverified(client, app):
    client.post("/register", data={"role": "company", "name": "HR", "email": "hr@co.local", "company_name": "Co",
                                   "password": "abcd1234", "confirm_password": "abcd1234"})
    c = CompanyProfile.query.one()
    assert c.company_name == "Co" and c.is_verified is False


def test_register_rejects_admin_role_and_bad_input(client, app):
    # role=admin from the form must never create an admin
    client.post("/register", data={"role": "admin", "name": "Evil", "email": "evil@test.local",
                                   "password": "abcd1234", "confirm_password": "abcd1234"})
    assert User.query.filter_by(role=Role.ADMIN).count() == 0
    r = client.post("/register", data={"role": "student", "name": "X", "email": "bad",
                                       "password": "short", "confirm_password": "nope"})
    assert r.status_code == 400
    assert b"valid email" in r.data


def test_duplicate_email_rejected(client, app):
    make_student(email="dup@test.local")
    r = client.post("/register", data={"role": "student", "name": "Dup", "email": "dup@test.local",
                                       "password": "abcd1234", "confirm_password": "abcd1234"})
    assert r.status_code == 400
    assert User.query.filter_by(email="dup@test.local").count() == 1


def test_login_success_and_failure(client, app):
    make_student(email="s1@test.local")
    assert login(client, "s1@test.local", "wrong").status_code == 401
    r = login(client, "s1@test.local")
    assert r.status_code == 302 and "/dashboard" in r.headers["Location"]
    assert client.get("/student/dashboard").status_code == 200


def test_login_lockout_after_repeated_failures(client, app):
    make_student(email="lock@test.local")
    for _ in range(app.config["LOGIN_MAX_ATTEMPTS"]):
        login(client, "lock@test.local", "bad-password")
    r = login(client, "lock@test.local")  # correct password but locked
    assert r.status_code == 429
    assert User.query.filter_by(email="lock@test.local").one().is_locked()


def test_inactive_user_cannot_login(client, app, db):
    make_user(Role.STUDENT, "off@test.local", active=False)
    db.session.commit()
    assert login(client, "off@test.local").status_code == 403


def test_logout_requires_post_and_clears_session(client, app):
    make_student(email="out@test.local")
    login(client, "out@test.local")
    assert client.get("/logout").status_code == 405
    client.post("/logout")
    r = client.get("/student/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_open_redirect_blocked(client, app):
    make_student(email="redir@test.local")
    r = client.post("/login?next=https://evil.example", data={"email": "redir@test.local", "password": PASSWORD})
    assert "evil.example" not in r.headers["Location"]
