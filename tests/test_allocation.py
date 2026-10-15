import pytest

from app.models import (Allocation, AllocationRun, AllocationStatus, Application, AppStatus, Notification,
                        RunStatus)
from app.services import allocation as alloc
from app.services.settings import save_settings
from tests.conftest import login, make_admin, make_company, make_internship, make_student


def apply(db, student, internship, rank=1, status=AppStatus.SUBMITTED):
    a = Application(student_id=student.id, internship_id=internship.id, preference_rank=rank, status=status)
    db.session.add(a)
    db.session.commit()
    return a


def run_and_confirm(admin):
    run = alloc.create_preview(admin)
    alloc.confirm_run(run, admin)
    return run


def test_deferred_acceptance_pure():
    prefs = {"s1": ["A", "B"], "s2": ["A"], "s3": ["A", "B"]}
    prio = {("A", "s1"): 2, ("A", "s2"): 1, ("A", "s3"): 3, ("B", "s1"): 1, ("B", "s3"): 2}
    held = alloc.deferred_acceptance(prefs, prio, {"A": 1, "B": 1}, {"s1": 1, "s2": 1, "s3": 1})
    assert held["A"] == {"s2"} and held["B"] == {"s1"}


def test_seat_limits_respected(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python", "SQL"), seats=2)
    students = [make_student(email=f"s{n}@t.local", skills=["Python", "SQL"] if n < 3 else ["Python"],
                             cgpa=6 + n * 0.5) for n in range(4)]
    for s in students:
        apply(db, s, i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    proposed = [a for a in run.allocations]
    assert len(proposed) == 2
    # the two candidates with both skills and highest CGPA win
    assert {a.student_id for a in proposed} == {students[2].id, students[1].id}
    alloc.confirm_run(run, admin)
    assert Allocation.query.filter_by(internship_id=i.id, status=AllocationStatus.ACTIVE).count() == 2
    assert i.seats_left() == 0


def test_student_preferences_and_not_greedy(app, db):
    """Top scorer prefers B, so A goes to the other student instead of greedily to the top scorer."""
    admin = make_admin()
    c = make_company()
    a_ = make_internship(c, "A", required=("Python",), seats=1)
    b_ = make_internship(c, "B", required=("Python",), seats=1)
    star = make_student(email="star@t.local", skills=["Python"], cgpa=9.8)
    other = make_student(email="other@t.local", skills=["Python"], cgpa=6.0)
    apply(db, star, a_, rank=2)
    apply(db, star, b_, rank=1)
    apply(db, other, a_, rank=1)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    got = {(x.student_id, x.internship_id) for x in run.allocations}
    assert got == {(star.id, b_.id), (other.id, a_.id)}


def test_falls_back_to_second_choice(app, db):
    admin = make_admin()
    c = make_company()
    a_ = make_internship(c, "A", required=("Python",), seats=1)
    b_ = make_internship(c, "B", required=("Python",), seats=1)
    strong = make_student(email="strong@t.local", skills=["Python"], cgpa=9.5)
    weak = make_student(email="weak@t.local", skills=["Python"], cgpa=6.5)
    apply(db, strong, a_, rank=1)
    apply(db, weak, a_, rank=1)
    apply(db, weak, b_, rank=2)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    got = {(x.student_id, x.internship_id) for x in run.allocations}
    assert got == {(strong.id, a_.id), (weak.id, b_.id)}


def test_one_allocation_per_student_and_no_duplicates_on_rerun(app, db):
    admin = make_admin()
    c = make_company()
    ints = [make_internship(c, f"I{n}", required=("Python",), seats=3) for n in range(3)]
    s = make_student(skills=["Python"])
    for n, i in enumerate(ints):
        apply(db, s, i, rank=n + 1)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run_and_confirm(admin)
    assert Allocation.query.filter_by(student_id=s.id, status=AllocationStatus.ACTIVE).count() == 1
    assert Allocation.query.filter_by(status=AllocationStatus.ACTIVE).one().internship_id == ints[0].id
    run2 = alloc.create_preview(admin)  # student already holds the max
    assert len(run2.allocations) == 0
    assert any("maximum" in u["reason"] for u in run2.summary["unallocated"])


def test_max_allocations_configurable(app, db):
    admin = make_admin()
    c = make_company()
    i1 = make_internship(c, "I1", required=("Python",))
    i2 = make_internship(c, "I2", required=("Python",))
    s = make_student(skills=["Python"])
    apply(db, s, i1, 1)
    apply(db, s, i2, 2)
    save_settings({"min_match_score": 0, "max_allocations_per_student": 2})
    db.session.commit()
    run = alloc.create_preview(admin)
    assert len(run.allocations) == 2


def test_min_score_and_eligibility_filters(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python", "SQL", "Flask"), seats=5, min_cgpa=7.0)
    low_cgpa = make_student(email="low@t.local", skills=["Python", "SQL", "Flask"], cgpa=6.0)
    no_skills = make_student(email="none@t.local", skills=["Photoshop"], cgpa=9.0)
    good = make_student(email="good@t.local", skills=["Python", "SQL", "Flask"], cgpa=8.0)
    for s in (low_cgpa, no_skills, good):
        apply(db, s, i)
    save_settings({"min_match_score": 40})
    db.session.commit()
    run = alloc.create_preview(admin)
    assert [a.student_id for a in run.allocations] == [good.id]
    reasons = {u["student_id"]: u["reason"] for u in run.summary["unallocated"]}
    assert "eligible" in reasons[low_cgpa.id]
    assert "below the minimum" in reasons[no_skills.id]


def test_rejected_and_withdrawn_excluded_and_company_priority(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",), seats=1)
    top = make_student(email="top@t.local", skills=["Python"], cgpa=9.9)
    picked = make_student(email="picked@t.local", skills=["Python"], cgpa=6.0)
    gone = make_student(email="gone@t.local", skills=["Python"], cgpa=9.0)
    apply(db, top, i)
    apply(db, picked, i, status=AppStatus.SELECTED)  # company selected => higher priority tier
    apply(db, gone, i, status=AppStatus.REJECTED)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    assert [a.student_id for a in run.allocations] == [picked.id]


def test_tie_break_is_deterministic(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",), seats=1)
    first = make_student(email="first@t.local", skills=["Python"], cgpa=8.0)
    second = make_student(email="second@t.local", skills=["Python"], cgpa=8.0)
    apply(db, first, i)
    apply(db, second, i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    winners = {alloc.create_preview(admin).allocations[0].student_id for _ in range(3)}
    assert winners == {first.id}  # identical score & CGPA -> earlier application / lower id wins


def test_preview_is_not_binding_and_confirm_is(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",))
    s = make_student(skills=["Python"])
    a = apply(db, s, i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    assert run.status == RunStatus.PREVIEW
    assert Allocation.query.filter_by(status=AllocationStatus.ACTIVE).count() == 0
    assert db.session.get(Application, a.id).status == AppStatus.SUBMITTED
    assert Notification.query.filter_by(category="allocation").count() == 0
    confirmed, skipped = alloc.confirm_run(run, admin)
    assert (confirmed, skipped) == (1, 0)
    assert db.session.get(Application, a.id).status == AppStatus.ALLOCATED
    assert Notification.query.filter_by(category="allocation").count() == 2  # student + company
    with pytest.raises(alloc.AllocationError):
        alloc.confirm_run(run, admin)  # cannot confirm twice


def test_confirm_revalidates_changed_data(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",), seats=1)
    s1 = make_student(email="a@t.local", skills=["Python"])
    s2 = make_student(email="b@t.local", skills=["Python"])
    apply(db, s1, i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    alloc.manual_allocate(s2, i, admin)  # seat taken after the preview
    confirmed, skipped = alloc.confirm_run(run, admin)
    assert (confirmed, skipped) == (0, 1)
    assert Allocation.query.filter_by(internship_id=i.id, status=AllocationStatus.ACTIVE).count() == 1


def test_confirm_is_atomic_on_failure(app, db, monkeypatch):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",), seats=2)
    for n in range(2):
        apply(db, make_student(email=f"x{n}@t.local", skills=["Python"]), i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run = alloc.create_preview(admin)
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(alloc, "notify", boom)
    with pytest.raises(RuntimeError):
        alloc.confirm_run(run, admin)
    assert Allocation.query.filter_by(status=AllocationStatus.ACTIVE).count() == 0
    assert Application.query.filter_by(status=AppStatus.ALLOCATED).count() == 0
    assert db.session.get(AllocationRun, run.id).status == RunStatus.FAILED


def test_cancel_and_manual_reassign(app, db):
    admin = make_admin()
    c = make_company()
    i1 = make_internship(c, "I1", required=("Python",), seats=1)
    i2 = make_internship(c, "I2", required=("Python",), seats=1)
    s = make_student(skills=["Python"])
    other = make_student(email="o@t.local", skills=["Python"])
    a = apply(db, s, i1)
    save_settings({"min_match_score": 0})
    db.session.commit()
    run_and_confirm(admin)
    current = Allocation.query.filter_by(status=AllocationStatus.ACTIVE).one()
    with pytest.raises(alloc.AllocationError):
        alloc.manual_allocate(s, i2, admin)  # would exceed one allocation per student
    with pytest.raises(alloc.AllocationError):
        alloc.manual_allocate(other, i1, admin)  # no seats left
    alloc.cancel_allocation(current, admin, "Student request")
    assert db.session.get(Application, a.id).status == AppStatus.SUBMITTED
    assert i1.seats_left() == 1
    alloc.manual_allocate(s, i2, admin, "Reassigned")
    assert Allocation.query.filter_by(student_id=s.id, status=AllocationStatus.ACTIVE).one().internship_id == i2.id


def test_conflict_detection(app, db):
    admin = make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",), seats=2)
    for n in range(2):
        alloc.manual_allocate(make_student(email=f"m{n}@t.local", skills=["Python"]), i, admin)
    i.seats = 1  # admin reduced seats after allocating
    db.session.commit()
    conflicts = alloc.find_conflicts()
    assert conflicts["over_capacity"][0]["allocated"] == 2


def test_admin_allocation_pages_flow(client, app, db):
    make_admin()
    c = make_company()
    i = make_internship(c, required=("Python",))
    apply(db, make_student(skills=["Python"]), i)
    save_settings({"min_match_score": 0})
    db.session.commit()
    login(client, "admin@test.local")
    r = client.post("/admin/allocation/preview")
    assert r.status_code == 302
    run = AllocationRun.query.one()
    assert client.get(f"/admin/allocation/runs/{run.id}").status_code == 200
    r = client.get(f"/admin/allocation/runs/{run.id}/report.csv")
    assert r.status_code == 200 and b"Student" in r.data
    client.post(f"/admin/allocation/runs/{run.id}/confirm")
    assert db.session.get(AllocationRun, run.id).status == RunStatus.CONFIRMED
