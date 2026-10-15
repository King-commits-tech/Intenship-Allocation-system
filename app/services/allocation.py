"""Automatic internship allocation.

Policy: **student-proposing deferred acceptance** (Gale-Shapley, many-to-many with capacities).

* Candidates are applications whose status is submitted / shortlisted / selected (or only
  shortlisted / selected when ``allocation_only_shortlisted`` = 1), whose student is eligible
  for the internship and whose match score is >= ``min_match_score``.
* Each student ranks their applications by their own ``preference_rank`` (1 = first choice),
  ties broken by match score (higher first) then internship id.
* Each internship ranks proposers by a deterministic priority key:
    1. company review tier: selected > shortlisted > submitted
    2. match score (higher first)
    3. CGPA (higher first, missing = 0)
    4. earlier application time
    5. lower student id (final, guaranteed tie-break)
* Capacity of an internship = seats - already active allocations.
* A student can hold at most ``max_allocations_per_student`` (minus allocations they already hold).
* The result is *stable*: no student and internship would both prefer each other over what
  they were given. It therefore respects seat limits, student preferences and company priorities
  rather than greedily giving every internship to the single highest scorer.

Running the engine creates a **preview** run (Allocation rows with status ``proposed``). Nothing
is binding until an admin confirms it; confirmation re-validates every proposal inside one
database transaction, so a failure leaves no partial records.
"""
import json
import logging
from collections import defaultdict

from app.extensions import db
from app.models import (Allocation, AllocationRun, AllocationStatus, Application, AppStatus, Internship,
                        InternshipStatus, RunStatus, StudentProfile, utcnow)
from app.services import match_service
from app.services.audit import log_action
from app.services.notifications import notify
from app.services.settings import get_all_settings

log = logging.getLogger(__name__)

REVIEW_TIER = {AppStatus.SELECTED: 0, AppStatus.SHORTLISTED: 1, AppStatus.SUBMITTED: 2}


class AllocationError(Exception):
    pass


def active_count_by_student():
    rows = db.session.query(Allocation.student_id, db.func.count(Allocation.id)).filter(
        Allocation.status == AllocationStatus.ACTIVE).group_by(Allocation.student_id).all()
    return dict(rows)


def active_count_by_internship():
    rows = db.session.query(Allocation.internship_id, db.func.count(Allocation.id)).filter(
        Allocation.status == AllocationStatus.ACTIVE).group_by(Allocation.internship_id).all()
    return dict(rows)


def active_pairs():
    return {(a.student_id, a.internship_id) for a in
            Allocation.query.filter_by(status=AllocationStatus.ACTIVE).all()}


def deferred_acceptance(student_prefs, internship_priority, capacity, quota):
    """Pure algorithm.

    student_prefs: {student: [internship, ...]} in preference order
    internship_priority: {(internship, student): sortable key} (smaller = better)
    capacity: {internship: int}
    quota: {student: int}
    Returns {internship: set(students)}.
    """
    held = defaultdict(set)
    held_count = defaultdict(int)
    pointer = defaultdict(int)
    queue = [s for s in student_prefs if quota.get(s, 0) > 0]
    while queue:
        s = queue.pop(0)
        prefs = student_prefs[s]
        while held_count[s] < quota.get(s, 0) and pointer[s] < len(prefs):
            i = prefs[pointer[s]]
            pointer[s] += 1
            if capacity.get(i, 0) <= 0:
                continue
            held[i].add(s)
            held_count[s] += 1
            if len(held[i]) > capacity[i]:
                worst = max(held[i], key=lambda x: internship_priority[(i, x)])
                held[i].discard(worst)
                held_count[worst] -= 1
                if worst != s and worst not in queue:
                    queue.append(worst)
    return held


def build_proposal():
    """Compute a proposed allocation from the current database state (no writes except score cache)."""
    settings = get_all_settings()
    min_score = settings["min_match_score"]
    max_per_student = settings["max_allocations_per_student"]
    pool = (AppStatus.SHORTLISTED, AppStatus.SELECTED) if settings["allocation_only_shortlisted"] else AppStatus.POOL

    internships = Internship.query.filter(
        Internship.status.in_([InternshipStatus.PUBLISHED, InternshipStatus.CLOSED])).all()
    taken = active_count_by_internship()
    capacity = {i.id: max(0, i.seats - taken.get(i.id, 0)) for i in internships}
    by_id = {i.id: i for i in internships}

    student_active = active_count_by_student()
    existing_pairs = active_pairs()

    apps = Application.query.filter(Application.status.in_(pool),
                                    Application.internship_id.in_(list(by_id) or [-1])).all()
    unallocated = {}  # student_id -> reason
    candidates = []
    # score in batches per internship (one TF-IDF fit per internship)
    grouped = defaultdict(list)
    for a in apps:
        grouped[a.internship_id].append(a)
    scores = {}
    for iid, group in grouped.items():
        scores.update(match_service.compute([a.student for a in group], [by_id[iid]]))

    for a in apps:
        r = scores[(a.student_id, a.internship_id)]
        if (a.student_id, a.internship_id) in existing_pairs:
            continue
        if not r["eligible"]:
            unallocated.setdefault(a.student_id, "Not eligible for the internships applied to.")
            continue
        if r["total"] < min_score:
            unallocated.setdefault(a.student_id, f"Match score below the minimum of {min_score:g}.")
            continue
        candidates.append((a, r))

    student_prefs = defaultdict(list)
    priority = {}
    info = {}
    for a, r in sorted(candidates, key=lambda t: (t[0].preference_rank, -t[1]["total"], t[0].internship_id)):
        student_prefs[a.student_id].append(a.internship_id)
        priority[(a.internship_id, a.student_id)] = (
            REVIEW_TIER.get(a.status, 3), -r["total"], -(a.student.cgpa or 0), a.created_at, a.student_id)
        info[(a.student_id, a.internship_id)] = (a, r)

    quota = {s: max(0, max_per_student - student_active.get(s, 0)) for s in student_prefs}
    for s, q in quota.items():
        if q == 0:
            unallocated[s] = "Already holds the maximum number of allocations."

    held = deferred_acceptance(student_prefs, priority, capacity, quota)

    proposals = []
    allocated_students = set()
    for iid, students in held.items():
        for sid in students:
            a, r = info[(sid, iid)]
            proposals.append({"application_id": a.id, "student_id": sid, "internship_id": iid,
                              "score": r["total"], "preference_rank": a.preference_rank})
            allocated_students.add(sid)
    for sid in student_prefs:
        if sid not in allocated_students and sid not in unallocated:
            unallocated[sid] = "Seats filled by higher-priority candidates."
    for sid in list(unallocated):
        if sid in allocated_students:
            unallocated.pop(sid)

    proposals.sort(key=lambda p: (p["internship_id"], -p["score"], p["student_id"]))
    fill = {iid: {"title": by_id[iid].title, "seats": by_id[iid].seats,
                  "already_allocated": taken.get(iid, 0),
                  "proposed": sum(1 for p in proposals if p["internship_id"] == iid)}
            for iid in by_id if grouped.get(iid) or taken.get(iid)}
    summary = {
        "applications_considered": len(apps),
        "eligible_candidates": len(candidates),
        "proposed_allocations": len(proposals),
        "students_allocated": len(allocated_students),
        "students_unallocated": len(unallocated),
        "unallocated": [{"student_id": k, "reason": v} for k, v in sorted(unallocated.items())],
        "internships": [{"internship_id": k, **v} for k, v in sorted(fill.items())],
        "average_score": round(sum(p["score"] for p in proposals) / len(proposals), 1) if proposals else 0,
    }
    params = {"min_match_score": min_score, "max_allocations_per_student": max_per_student,
              "statuses": list(pool)}
    return proposals, summary, params


def create_preview(admin_user):
    proposals, summary, params = build_proposal()
    run = AllocationRun(created_by_id=admin_user.id if admin_user else None, status=RunStatus.PREVIEW,
                        params_json=json.dumps(params), summary_json=json.dumps(summary))
    db.session.add(run)
    db.session.flush()
    for p in proposals:
        db.session.add(Allocation(run_id=run.id, student_id=p["student_id"], internship_id=p["internship_id"],
                                  application_id=p["application_id"], score=p["score"],
                                  status=AllocationStatus.PROPOSED,
                                  note=f"Preference #{p['preference_rank']}"))
    log_action("allocation.preview", "allocation_run", run.id,
               f"{len(proposals)} proposed allocations", user=admin_user)
    db.session.commit()
    return run


def confirm_run(run, admin_user):
    """Make a preview binding. Re-validates every proposal in a single transaction."""
    if run.status != RunStatus.PREVIEW:
        raise AllocationError("Only preview runs can be confirmed.")
    settings = get_all_settings()
    try:
        taken = active_count_by_internship()
        student_active = active_count_by_student()
        pairs = active_pairs()
        confirmed, skipped = [], []
        for alloc in sorted(run.allocations, key=lambda a: (-(a.score or 0), a.student_id)):
            if alloc.status != AllocationStatus.PROPOSED:
                continue
            app_ = alloc.application
            internship = alloc.internship
            reason = None
            if app_ is None or app_.status not in AppStatus.POOL:
                reason = "application no longer in the allocation pool"
            elif (alloc.student_id, alloc.internship_id) in pairs:
                reason = "student already allocated to this internship"
            elif taken.get(alloc.internship_id, 0) >= internship.seats:
                reason = "no seats left"
            elif student_active.get(alloc.student_id, 0) >= settings["max_allocations_per_student"]:
                reason = "student reached allocation limit"
            if reason:
                alloc.status = AllocationStatus.DISCARDED
                alloc.note = f"Skipped at confirmation: {reason}"
                skipped.append(alloc.id)
                continue
            alloc.status = AllocationStatus.ACTIVE
            app_.status = AppStatus.ALLOCATED
            taken[alloc.internship_id] = taken.get(alloc.internship_id, 0) + 1
            student_active[alloc.student_id] = student_active.get(alloc.student_id, 0) + 1
            pairs.add((alloc.student_id, alloc.internship_id))
            confirmed.append(alloc)
            notify(alloc.student.user, "Internship allocated",
                   f"You have been allocated to {internship.title} at {internship.company.company_name}.",
                   "allocation", "/student/allocations")
            notify(internship.company.user, "Candidate allocated",
                   f"{alloc.student.user.name} has been allocated to {internship.title}.",
                   "allocation", "/company/allocations")
        summary = run.summary
        summary["confirmed"] = len(confirmed)
        summary["skipped_at_confirmation"] = len(skipped)
        run.summary_json = json.dumps(summary)
        run.status = RunStatus.CONFIRMED
        run.confirmed_at = utcnow()
        # Any other open previews were computed against old data - discard them.
        for other in AllocationRun.query.filter(AllocationRun.status == RunStatus.PREVIEW,
                                                AllocationRun.id != run.id).all():
            _discard(other)
        log_action("allocation.confirm", "allocation_run", run.id,
                   f"confirmed={len(confirmed)} skipped={len(skipped)}", user=admin_user)
        db.session.commit()
        return len(confirmed), len(skipped)
    except Exception:
        db.session.rollback()
        log.exception("Allocation confirmation failed for run %s", run.id)
        failed = db.session.get(AllocationRun, run.id)
        if failed is not None:
            failed.status = RunStatus.FAILED
            db.session.commit()
        raise


def _discard(run):
    run.status = RunStatus.DISCARDED
    for a in run.allocations:
        if a.status == AllocationStatus.PROPOSED:
            a.status = AllocationStatus.DISCARDED


def discard_run(run, admin_user):
    if run.status != RunStatus.PREVIEW:
        raise AllocationError("Only preview runs can be discarded.")
    _discard(run)
    log_action("allocation.discard", "allocation_run", run.id, user=admin_user)
    db.session.commit()


def cancel_allocation(alloc, admin_user, reason=""):
    if alloc.status != AllocationStatus.ACTIVE:
        raise AllocationError("Only active allocations can be cancelled.")
    alloc.status = AllocationStatus.CANCELLED
    alloc.cancelled_at = utcnow()
    alloc.cancelled_by_id = admin_user.id
    alloc.note = ("Cancelled: " + reason)[:255] if reason else "Cancelled by administrator"
    if alloc.application and alloc.application.status == AppStatus.ALLOCATED:
        alloc.application.status = AppStatus.SUBMITTED  # back into the pool for future runs
    notify(alloc.student.user, "Allocation cancelled",
           f"Your allocation to {alloc.internship.title} was cancelled. {reason}".strip(), "allocation",
           "/student/allocations")
    notify(alloc.internship.company.user, "Allocation cancelled",
           f"{alloc.student.user.name}'s allocation to {alloc.internship.title} was cancelled.", "allocation",
           "/company/allocations")
    log_action("allocation.cancel", "allocation", alloc.id, reason, user=admin_user)
    db.session.commit()


def manual_allocate(student: StudentProfile, internship: Internship, admin_user, note=""):
    """Authorised reassignment / manual allocation with the same seat and conflict checks."""
    settings = get_all_settings()
    if internship.status == InternshipStatus.DRAFT:
        raise AllocationError("Cannot allocate to a draft internship.")
    if Allocation.query.filter_by(student_id=student.id, internship_id=internship.id,
                                  status=AllocationStatus.ACTIVE).first():
        raise AllocationError("Student is already allocated to this internship.")
    if internship.seats_left() <= 0:
        raise AllocationError("No seats left for this internship.")
    current = Allocation.query.filter_by(student_id=student.id, status=AllocationStatus.ACTIVE).count()
    if current >= settings["max_allocations_per_student"]:
        raise AllocationError("Student already holds the maximum number of allocations. Cancel one first.")
    result = match_service.match_for(student, internship)
    app_ = Application.query.filter_by(student_id=student.id, internship_id=internship.id).first()
    if app_ is None:
        app_ = Application(student_id=student.id, internship_id=internship.id, preference_rank=1,
                           cover_note="Created by administrator during manual allocation.")
        db.session.add(app_)
        db.session.flush()
    app_.status = AppStatus.ALLOCATED
    alloc = Allocation(run_id=None, student_id=student.id, internship_id=internship.id, application_id=app_.id,
                       score=result["total"], status=AllocationStatus.ACTIVE,
                       note=("Manual: " + note)[:255] if note else "Manual allocation by administrator")
    db.session.add(alloc)
    notify(student.user, "Internship allocated",
           f"You have been allocated to {internship.title} at {internship.company.company_name}.",
           "allocation", "/student/allocations")
    notify(internship.company.user, "Candidate allocated",
           f"{student.user.name} has been allocated to {internship.title}.", "allocation", "/company/allocations")
    log_action("allocation.manual", "allocation", None,
               f"student={student.id} internship={internship.id} score={result['total']}", user=admin_user)
    db.session.commit()
    return alloc


def find_conflicts():
    """Detect states that violate the policy (e.g. after seats or limits were lowered)."""
    max_per_student = get_all_settings()["max_allocations_per_student"]
    over_capacity = []
    for iid, count in active_count_by_internship().items():
        i = db.session.get(Internship, iid)
        if i and count > i.seats:
            over_capacity.append({"internship": i, "allocated": count})
    over_quota = []
    for sid, count in active_count_by_student().items():
        if count > max_per_student:
            over_quota.append({"student": db.session.get(StudentProfile, sid), "allocated": count})
    return {"over_capacity": over_capacity, "over_quota": over_quota}
