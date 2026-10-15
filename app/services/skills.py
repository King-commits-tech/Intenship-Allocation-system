"""Skill dictionary, normalisation and NLP-style skill extraction.

Matching is rule based and transparent: every canonical skill has a list of
aliases (``app/data/skills.json``). Free text is lower-cased and each alias is
searched as a whole "word" (letters, digits, ``+``, ``#`` and ``.`` count as part
of a word so that ``C`` does not match inside ``C++``).

Short / ambiguous aliases (``C``, ``R``, ``Go``, ``Swift`` ...) only match free
text when they are written with an upper-case letter, which avoids false hits
on ordinary English words ("go", "swift", "spring").
"""
import json
import os
import re
from functools import lru_cache

from flask import current_app

# Aliases that are also common English words / letters. In free text they must
# appear with at least one upper-case character to count.
AMBIGUOUS = {"c", "r", "go", "swift", "spring", "express", "node", "rest", "torch", "spark", "qa", "sem",
             "seo", "ml", "js", "os", "eda", "dart", "ios", "hadoop", "mongo", "unix", "bash", "probability",
             "excel", "leadership", "teamwork", "communication", "collaboration", "containers",
             "networking", "algorithms", "statistics", "prototyping", "wireframing", "unittest"}
# Short aliases accepted when a user *types a skill* but never searched for in free text
# (they collide with ordinary words/abbreviations in resumes, e.g. "CV").
INPUT_ONLY_ALIASES = {"py": "Python", "ts": "TypeScript", "dl": "Deep Learning", "xd": "Adobe XD"}
_WORD_CHARS = r"A-Za-z0-9+#"


def _load_dictionary(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    skills = data.get("skills", data)
    canonical = {}
    alias_map = {}
    for name, meta in skills.items():
        if name.startswith("_"):
            continue
        meta = meta or {}
        canonical[name] = meta.get("category") or "Other"
        alias_map[name.lower()] = name
        for alias in meta.get("aliases", []):
            alias_map[alias.lower().strip()] = name
    return canonical, alias_map


@lru_cache(maxsize=4)
def _cached_dictionary(path, mtime):
    return _load_dictionary(path)


def _dict_path():
    path = current_app.config.get("SKILLS_FILE")
    if not path or not os.path.exists(path):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "skills.json")
    return path


def get_dictionary():
    path = _dict_path()
    return _cached_dictionary(path, os.path.getmtime(path))


def all_skill_names():
    canonical, _ = get_dictionary()
    return sorted(canonical)


def category_of(skill_name):
    canonical, _ = get_dictionary()
    return canonical.get(skill_name, "Other")


def _clean(text):
    return re.sub(r"\s+", " ", (text or "").strip().strip(".,;:")).strip()


def normalize_skill(raw):
    """Map a user supplied skill to its canonical name.

    Unknown skills are kept (title-cased) so students are not limited to the dictionary.
    Returns ``None`` for empty / overly long input.
    """
    value = _clean(raw)
    if not value or len(value) > 60:
        return None
    _, alias_map = get_dictionary()
    hit = alias_map.get(value.lower()) or INPUT_ONLY_ALIASES.get(value.lower())
    if hit:
        return hit
    # Keep acronyms as typed, otherwise use title case
    return value if (value.isupper() and len(value) <= 6) else value[:1].upper() + value[1:]


def parse_skill_list(text):
    """Split a comma / newline / semicolon separated list and normalise each item (deduplicated, ordered)."""
    seen, result = set(), []
    for part in re.split(r"[,\n;|]+", text or ""):
        skill = normalize_skill(part)
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            result.append(skill)
    return result


@lru_cache(maxsize=4)
def _compiled_patterns(path, mtime):
    canonical, alias_map = _load_dictionary(path)
    patterns = []
    for alias, name in alias_map.items():
        escaped = re.escape(alias).replace(r"\ ", r"[\s\-]+")
        # word boundary that treats + # as word characters; a trailing '.' is allowed (end of sentence)
        regex = rf"(?<![{_WORD_CHARS}]){escaped}(?![{_WORD_CHARS}]|\.[A-Za-z])"
        patterns.append((alias, name, re.compile(regex, re.IGNORECASE)))
    return patterns


def extract_skills(text):
    """Return sorted canonical skills mentioned in free text (resume, projects, descriptions)."""
    if not text or not text.strip():
        return []
    path = _dict_path()
    found = set()
    for alias, name, pattern in _compiled_patterns(path, os.path.getmtime(path)):
        if name in found:
            continue
        for m in pattern.finditer(text):
            token = m.group(0)
            if alias in AMBIGUOUS and token.islower():
                continue
            found.add(name)
            break
    return sorted(found)


def related_skills(skill_name, limit=3, exclude=()):
    """Suggest skills from the same category (used for 'skills to improve')."""
    canonical, _ = get_dictionary()
    cat = canonical.get(skill_name)
    if not cat:
        return []
    exclude = {e.lower() for e in exclude} | {skill_name.lower()}
    return [s for s in sorted(canonical) if canonical[s] == cat and s.lower() not in exclude][:limit]


def get_or_create_skill(name):
    """Return the Skill row for a canonical name, creating it if needed (caller commits)."""
    from app.extensions import db
    from app.models import Skill

    name = normalize_skill(name)
    if not name:
        return None
    skill = Skill.query.filter(db.func.lower(Skill.name) == name.lower()).first()
    if skill is None:
        skill = Skill(name=name, category=category_of(name))
        db.session.add(skill)
        db.session.flush()
    return skill
