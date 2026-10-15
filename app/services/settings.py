"""Typed access to the key/value Setting table with documented defaults."""
from app.extensions import db
from app.models import Setting

DEFAULTS = {
    # Matching weights (relative; they are normalised so they need not sum to 100)
    "weight_skills": 50.0,
    "weight_projects": 20.0,
    "weight_interests": 15.0,
    "weight_academics": 15.0,
    # Allocation policy
    "max_allocations_per_student": 1,
    "min_match_score": 30.0,          # proposals below this score are not allocated
    "allocation_only_shortlisted": 0,  # 1 = only shortlisted/selected applications are considered
}

LABELS = {
    "weight_skills": "Weight: required & relevant skills",
    "weight_projects": "Weight: projects & experience",
    "weight_interests": "Weight: interests & domain preference",
    "weight_academics": "Weight: academic performance",
    "max_allocations_per_student": "Max simultaneous allocations per student",
    "min_match_score": "Minimum match score for allocation (0-100)",
    "allocation_only_shortlisted": "Only allocate shortlisted/selected applications (1 = yes, 0 = no)",
}

_INT_KEYS = {"max_allocations_per_student", "allocation_only_shortlisted"}


def _coerce(key, value):
    return int(float(value)) if key in _INT_KEYS else float(value)


def get_setting(key):
    row = db.session.get(Setting, key)
    if row is None:
        return DEFAULTS[key]
    try:
        return _coerce(key, row.value)
    except (TypeError, ValueError):
        return DEFAULTS[key]


def get_all_settings():
    return {k: get_setting(k) for k in DEFAULTS}


def validate_settings(values):
    """Return (clean_values, errors)."""
    clean, errors = {}, []
    for key in DEFAULTS:
        if key not in values:
            continue
        try:
            v = _coerce(key, values[key])
        except (TypeError, ValueError):
            errors.append(f"{LABELS[key]} must be a number.")
            continue
        if key.startswith("weight_") and not 0 <= v <= 100:
            errors.append(f"{LABELS[key]} must be between 0 and 100.")
        elif key == "max_allocations_per_student" and not 1 <= v <= 5:
            errors.append("Max allocations per student must be between 1 and 5.")
        elif key == "min_match_score" and not 0 <= v <= 100:
            errors.append("Minimum match score must be between 0 and 100.")
        elif key == "allocation_only_shortlisted" and v not in (0, 1):
            errors.append("Only-shortlisted must be 0 or 1.")
        clean[key] = v
    weight_sum = sum(clean.get(k, get_setting(k)) for k in DEFAULTS if k.startswith("weight_"))
    if weight_sum <= 0:
        errors.append("At least one matching weight must be greater than zero.")
    return clean, errors


def save_settings(values):
    for key, value in values.items():
        row = db.session.get(Setting, key)
        if row is None:
            db.session.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)


def get_weights():
    return {
        "skills": get_setting("weight_skills"),
        "projects": get_setting("weight_projects"),
        "interests": get_setting("weight_interests"),
        "academics": get_setting("weight_academics"),
    }
