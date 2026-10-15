from app.services import match_service
from app.services.matching import InternshipDoc, StudentDoc, check_eligibility, score_one
from app.services.settings import save_settings
from app.services.skills import extract_skills, normalize_skill, parse_skill_list
from tests.conftest import make_company, make_internship, make_student


def test_skill_normalisation(app):
    assert normalize_skill("js") == "JavaScript"
    assert normalize_skill(" ML ") == "Machine Learning"
    assert normalize_skill("ReactJS") == "React"
    assert normalize_skill("k8s") == "Kubernetes"
    assert normalize_skill("brand new skill") == "Brand new skill"
    assert normalize_skill("") is None
    assert parse_skill_list("Python, python3; py,\nSQL") == ["Python", "SQL"]


def test_skill_extraction_handles_symbols_and_ambiguity(app):
    text = "Worked with C++ and C#, plus Node.js. I like to go hiking. Wrote code in C and Go."
    found = extract_skills(text)
    assert {"C++", "C#", "Node.js", "C", "Go"} <= set(found)
    assert "Go" not in extract_skills("I will go to the market and express my views")
    assert "C" not in extract_skills("Only C++ here")
    assert extract_skills("") == [] and extract_skills(None) == []


def _student(**kw):
    base = dict(id=1, skills=["Python", "SQL", "Flask"], projects="Built a Flask REST API with SQL",
                interests="web development", preferred_domain="Web Development", cgpa=8.0,
                department="Computer Science", year_of_study=3)
    base.update(kw)
    return StudentDoc(**base)


def _internship(**kw):
    base = dict(id=10, title="Backend Intern", description="Build Flask REST APIs backed by SQL databases",
                domain="Web Development", required_skills=["Python", "Flask", "SQL"], preferred_skills=["Docker"])
    base.update(kw)
    return InternshipDoc(**base)


def test_score_range_components_and_explanation(app):
    r = score_one(_student(), _internship())
    assert 0 <= r["total"] <= 100
    assert r["total"] > 60
    assert r["eligible"]
    assert r["matched_skills"] == ["Flask", "Python", "SQL"]
    assert r["missing_required"] == [] and r["missing_preferred"] == ["Docker"]
    assert "Docker" in r["suggestions"]
    assert set(r["components"]) == {"skills", "projects", "interests", "academics"}
    assert any("required skills" in s for s in r["strengths"])
    # skills component: 0.75*1 + 0.25*0 = 75
    assert r["components"]["skills"] == 75.0
    assert r["components"]["academics"] == 80.0


def test_better_profile_scores_higher(app):
    strong = score_one(_student(), _internship())
    weak = score_one(_student(id=2, skills=["Photoshop"], projects="", interests="", preferred_domain="", cgpa=6.0),
                     _internship())
    assert strong["total"] > weak["total"] + 30
    assert weak["missing_required"] == ["Flask", "Python", "SQL"]


def test_empty_profile_does_not_crash(app):
    empty = StudentDoc(id=3)
    r = score_one(empty, _internship())
    assert 0 <= r["total"] <= 100
    assert any("No skills" in g for g in r["gaps"])
    assert r["components"]["academics"] == 50.0  # neutral when missing
    r2 = score_one(empty, InternshipDoc(id=11))  # internship with no text at all
    assert 0 <= r2["total"] <= 100


def test_hard_eligibility_only_when_specified(app):
    ok, _ = check_eligibility(_student(cgpa=6.0), _internship())
    assert ok  # no rules => eligible, even with missing optional skills
    ok, reasons = check_eligibility(_student(cgpa=6.0), _internship(min_cgpa=7.0))
    assert not ok and "below" in reasons[0]
    ok, reasons = check_eligibility(_student(cgpa=None), _internship(min_cgpa=7.0))
    assert not ok and "no CGPA" in reasons[0]
    ok, _ = check_eligibility(_student(department="Mechanical"), _internship(departments=["Computer Science"]))
    assert not ok
    ok, _ = check_eligibility(_student(year_of_study=2), _internship(years=[3, 4]))
    assert not ok


def test_missing_optional_skill_never_ineligible(app):
    r = score_one(_student(skills=["Python", "Flask", "SQL"]), _internship(preferred_skills=["Kubernetes", "AWS"]))
    assert r["eligible"]


def test_configurable_weights_change_scores(app, db):
    s = _student(cgpa=10.0, skills=[])
    default = score_one(s, _internship())["total"]
    only_academics = score_one(s, _internship(), {"skills": 0, "projects": 0, "interests": 0, "academics": 1})
    assert only_academics["total"] == 100.0
    assert default < 100.0
    # weights stored in settings are used by the DB layer
    company = make_company()
    i = make_internship(company)
    p = make_student(cgpa=10.0, skills=[])
    save_settings({"weight_skills": 0, "weight_projects": 0, "weight_interests": 0, "weight_academics": 10})
    db.session.commit()
    assert match_service.match_for(p, i)["total"] == 100.0


def test_recommendations_ranked_and_cached(app, db):
    from app.models import MatchScore
    c = make_company()
    web = make_internship(c, "Web Intern", required=("Python", "Flask", "SQL"), domain="Web Development")
    ml = make_internship(c, "ML Intern", required=("Machine Learning", "Pandas"), domain="Machine Learning")
    hard = make_internship(c, "Elite Intern", required=("Python",), min_cgpa=9.5)
    p = make_student(skills=["Python", "Flask", "SQL"], domain="Web Development", cgpa=8.0)
    recs = match_service.recommendations(p)
    db.session.commit()
    ids = [i.id for i, _ in recs]
    assert ids[0] == web.id
    assert hard.id not in ids  # ineligible hidden by default
    assert ml.id in ids
    all_recs = match_service.recommendations(p, include_ineligible=True)
    assert all_recs[-1][0].id == hard.id
    assert MatchScore.query.count() == 3


def test_rank_applicants(app, db):
    from app.models import Application
    c = make_company()
    i = make_internship(c, required=("Python", "SQL"))
    strong = make_student(email="a@t.local", skills=["Python", "SQL"], cgpa=9.0)
    weak = make_student(email="b@t.local", skills=["Excel"], cgpa=6.0)
    for s in (weak, strong):
        db.session.add(Application(student_id=s.id, internship_id=i.id))
    db.session.commit()
    rows = match_service.rank_applicants(i)
    assert [a.student_id for a, _ in rows] == [strong.id, weak.id]
