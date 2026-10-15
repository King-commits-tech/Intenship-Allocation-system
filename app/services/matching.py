"""Explainable, content-based internship matching engine.

No historical outcome data is assumed, so there is **no trained predictive model**.
Instead every score is a transparent weighted sum of four components, each in
the range 0..1:

    total = 100 * (Ws*skills + Wp*projects + Wi*interests + Wa*academics) / (Ws+Wp+Wi+Wa)

1. skills    - coverage of the internship's skills by the student's (normalised) skills:
               0.75 * required_coverage + 0.25 * preferred_coverage
               (if only one list exists it gets the full weight; if the internship lists no
               skills, TF-IDF text similarity of the whole profile is used instead).
2. projects  - evidence in projects / experience / certifications text:
               0.5 * (share of internship skills mentioned there) + 0.5 * scaled TF-IDF similarity.
3. interests - 0.5 * preferred-domain match + 0.4 * scaled TF-IDF similarity of the
               interests text with the internship + 0.1 * location / remote fit.
4. academics - CGPA / 10 (or percentage / 100). Missing academic data -> neutral 0.5.

"Scaled TF-IDF similarity" = min(1, cosine * SIM_SCALE). Cosine values between short
texts are naturally small, so they are scaled (SIM_SCALE = 2.5) before use.

Hard eligibility (minimum CGPA, departments, years of study) is only enforced when
the internship explicitly specifies it. Missing an optional/preferred skill never
makes a student ineligible.

Scores assist decision-making; they do not guarantee selection or employment.
"""
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services.skills import extract_skills, related_skills

SIM_SCALE = 2.5
DEFAULT_WEIGHTS = {"skills": 50.0, "projects": 20.0, "interests": 15.0, "academics": 15.0}


@dataclass
class StudentDoc:
    id: int
    skills: list = field(default_factory=list)
    resume_text: str = ""
    projects: str = ""
    experience: str = ""
    certifications: str = ""
    interests: str = ""
    preferred_domain: str = ""
    preferred_location: str = ""
    cgpa: float = None
    percentage: float = None
    department: str = ""
    year_of_study: int = None

    @property
    def project_text(self):
        return " ".join(filter(None, [self.projects, self.experience, self.certifications]))

    @property
    def interest_text(self):
        return " ".join(filter(None, [self.interests, self.preferred_domain]))

    @property
    def full_text(self):
        return " ".join(filter(None, [" ".join(self.skills), self.project_text, self.interest_text,
                                      self.resume_text]))


@dataclass
class InternshipDoc:
    id: int
    title: str = ""
    description: str = ""
    domain: str = ""
    location: str = ""
    work_mode: str = ""
    required_skills: list = field(default_factory=list)
    preferred_skills: list = field(default_factory=list)
    min_cgpa: float = None
    departments: list = field(default_factory=list)
    years: list = field(default_factory=list)

    @property
    def text(self):
        return " ".join(filter(None, [self.title, self.domain, self.description,
                                      " ".join(self.required_skills), " ".join(self.preferred_skills)]))


def normalize_weights(weights):
    w = {k: max(0.0, float((weights or {}).get(k, DEFAULT_WEIGHTS[k]))) for k in DEFAULT_WEIGHTS}
    total = sum(w.values())
    if total <= 0:
        w, total = dict(DEFAULT_WEIGHTS), sum(DEFAULT_WEIGHTS.values())
    return {k: v / total for k, v in w.items()}


def check_eligibility(student, internship):
    """Return (eligible, reasons). Only rules explicitly set on the internship are applied."""
    reasons = []
    if internship.min_cgpa is not None:
        if student.cgpa is None:
            reasons.append(f"Requires minimum CGPA {internship.min_cgpa:g}, but no CGPA is on the profile.")
        elif student.cgpa < internship.min_cgpa:
            reasons.append(f"CGPA {student.cgpa:g} is below the required {internship.min_cgpa:g}.")
    if internship.departments:
        allowed = {d.lower() for d in internship.departments}
        if not student.department:
            reasons.append("Open only to " + ", ".join(internship.departments) + " (department not on profile).")
        elif student.department.lower() not in allowed:
            reasons.append(f"Open only to {', '.join(internship.departments)}; your department is "
                           f"{student.department}.")
    if internship.years:
        if student.year_of_study is None:
            reasons.append("Open only to year(s) " + ", ".join(map(str, internship.years))
                           + " (year of study not on profile).")
        elif student.year_of_study not in internship.years:
            reasons.append(f"Open only to year(s) {', '.join(map(str, internship.years))}; you are in "
                           f"year {student.year_of_study}.")
    return (not reasons), reasons


class _Similarity:
    """Fits one TF-IDF vocabulary over every document in the batch and serves cosine lookups."""

    def __init__(self, texts):
        self.index = {}
        docs = []
        for key, text in texts.items():
            self.index[key] = len(docs)
            docs.append(text or "")
        self.matrix = None
        if any(d.strip() for d in docs):
            try:
                vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2),
                                      token_pattern=r"(?u)\b[\w\+\#\.]*\w[\w\+\#]*\b")
                self.matrix = vec.fit_transform(docs)
            except ValueError:  # empty vocabulary (only stop words)
                self.matrix = None

    def cos(self, a, b):
        if self.matrix is None or a not in self.index or b not in self.index:
            return 0.0
        return float(cosine_similarity(self.matrix[self.index[a]], self.matrix[self.index[b]])[0, 0])


def _lower_set(items):
    return {i.lower(): i for i in items if i}


def _score_pair(s, i, sim, weights):
    w = normalize_weights(weights)
    strengths, gaps = [], []

    # ---------------- skills ----------------
    student_skills = _lower_set(s.skills)
    req, pref = _lower_set(i.required_skills), _lower_set(i.preferred_skills)
    matched_req = [req[k] for k in req if k in student_skills]
    matched_pref = [pref[k] for k in pref if k in student_skills]
    missing_req = [req[k] for k in req if k not in student_skills]
    missing_pref = [pref[k] for k in pref if k not in student_skills]
    full_sim = min(1.0, sim.cos(("s_full", s.id), ("i", i.id)) * SIM_SCALE)
    if req and pref:
        skill = 0.75 * len(matched_req) / len(req) + 0.25 * len(matched_pref) / len(pref)
    elif req:
        skill = len(matched_req) / len(req)
    elif pref:
        skill = len(matched_pref) / len(pref)
    else:
        skill = full_sim
    if matched_req:
        strengths.append(f"Has {len(matched_req)} of {len(req)} required skills: {', '.join(sorted(matched_req))}.")
    if missing_req:
        gaps.append(f"Missing required skills: {', '.join(sorted(missing_req))}.")
    if matched_pref:
        strengths.append(f"Bonus skills: {', '.join(sorted(matched_pref))}.")
    if not s.skills:
        gaps.append("No skills on profile yet - add skills or upload a resume.")

    # ---------------- projects / experience ----------------
    all_internship_skills = {**req, **pref}
    if s.project_text.strip():
        evidence = _lower_set(extract_skills(s.project_text))
        used = [all_internship_skills[k] for k in all_internship_skills if k in evidence]
        proj_sim = min(1.0, sim.cos(("s_proj", s.id), ("i", i.id)) * SIM_SCALE)
        if all_internship_skills:
            project = 0.5 * len(used) / len(all_internship_skills) + 0.5 * proj_sim
        else:
            project = proj_sim
        if used:
            strengths.append(f"Projects/experience demonstrate {', '.join(sorted(used))}.")
        elif proj_sim >= 0.4:
            strengths.append("Project work is closely related to this internship.")
        else:
            gaps.append("Projects do not clearly show this internship's skills.")
    else:
        project = 0.0
        gaps.append("No projects, experience or certifications listed.")

    # ---------------- interests / domain ----------------
    domain_match = bool(s.preferred_domain and i.domain and s.preferred_domain.lower() == i.domain.lower())
    int_sim = min(1.0, sim.cos(("s_int", s.id), ("i", i.id)) * SIM_SCALE) if s.interest_text.strip() else 0.0
    if not s.preferred_location:
        loc_fit = 0.5
    elif (i.work_mode or "").lower() == "remote" or (
            i.location and s.preferred_location.lower() in i.location.lower()):
        loc_fit = 1.0
    else:
        loc_fit = 0.0
    interest = 0.5 * (1.0 if domain_match else 0.0) + 0.4 * int_sim + 0.1 * loc_fit
    if domain_match:
        strengths.append(f"Matches preferred domain ({i.domain}).")
    elif s.preferred_domain:
        gaps.append(f"Preferred domain is {s.preferred_domain}, this internship is {i.domain}.")
    if not s.interest_text.strip():
        gaps.append("No interests or preferred domain on profile.")

    # ---------------- academics ----------------
    if s.cgpa is not None:
        academic = max(0.0, min(1.0, s.cgpa / 10.0))
        if s.cgpa >= 8:
            strengths.append(f"Strong academics (CGPA {s.cgpa:g}).")
    elif s.percentage is not None:
        academic = max(0.0, min(1.0, s.percentage / 100.0))
    else:
        academic = 0.5
        gaps.append("No CGPA/percentage on profile; a neutral academic score was used.")

    eligible, reasons = check_eligibility(s, i)
    total = 100.0 * (w["skills"] * skill + w["projects"] * project + w["interests"] * interest
                     + w["academics"] * academic)
    total = round(max(0.0, min(100.0, total)), 1)

    suggestions = []
    for m in sorted(missing_req) + sorted(missing_pref):
        if m not in suggestions:
            suggestions.append(m)
    if not suggestions and s.skills:
        for sk in sorted(matched_req)[:2]:
            for rel in related_skills(sk, limit=2, exclude=s.skills):
                if rel not in suggestions:
                    suggestions.append(rel)

    if not eligible:
        summary = "Not eligible: " + " ".join(reasons)
    elif total >= 75:
        summary = "Excellent match"
    elif total >= 55:
        summary = "Good match"
    elif total >= 35:
        summary = "Partial match"
    else:
        summary = "Weak match"

    return {
        "student_id": s.id,
        "internship_id": i.id,
        "total": total,
        "components": {
            "skills": round(skill * 100, 1),
            "projects": round(project * 100, 1),
            "interests": round(interest * 100, 1),
            "academics": round(academic * 100, 1),
        },
        "weights": {k: round(v * 100, 1) for k, v in w.items()},
        "eligible": eligible,
        "eligibility_reasons": reasons,
        "matched_skills": sorted(matched_req + matched_pref),
        "missing_required": sorted(missing_req),
        "missing_preferred": sorted(missing_pref),
        "suggestions": suggestions[:6],
        "strengths": strengths,
        "gaps": gaps,
        "summary": summary,
    }


def score_matrix(students, internships, weights=None):
    """Score every (student, internship) pair. Returns {(student_id, internship_id): result}."""
    texts = {}
    for s in students:
        texts[("s_full", s.id)] = s.full_text
        texts[("s_proj", s.id)] = s.project_text
        texts[("s_int", s.id)] = s.interest_text
    for i in internships:
        texts[("i", i.id)] = i.text
    sim = _Similarity(texts)
    return {(s.id, i.id): _score_pair(s, i, sim, weights) for s in students for i in internships}


def score_one(student, internship, weights=None):
    return score_matrix([student], [internship], weights)[(student.id, internship.id)]
