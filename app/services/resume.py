"""Secure resume upload + PDF text extraction."""
import logging
import os
import secrets

from flask import current_app
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from werkzeug.utils import secure_filename

from app.services.skills import extract_skills

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
MAX_PAGES = 15


class ResumeError(ValueError):
    pass


def validate_upload(file_storage):
    """Validate extension, magic bytes and size. Returns raw bytes."""
    if file_storage is None or not file_storage.filename:
        raise ResumeError("Please choose a PDF file to upload.")
    name = secure_filename(file_storage.filename) or "resume.pdf"
    if not name.lower().endswith(".pdf"):
        raise ResumeError("Only PDF resumes are accepted.")
    data = file_storage.read()
    max_bytes = int(current_app.config["MAX_RESUME_MB"] * 1024 * 1024)
    if len(data) == 0:
        raise ResumeError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ResumeError(f"Resume is larger than {current_app.config['MAX_RESUME_MB']:g} MB.")
    if not data.startswith(PDF_MAGIC):
        raise ResumeError("The file is not a valid PDF document.")
    return name, data


def store_file(data):
    """Write bytes under a random name inside UPLOAD_FOLDER (never executed, never user-named)."""
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    stored = secrets.token_hex(16) + ".pdf"
    path = os.path.join(folder, stored)
    with open(path, "wb") as fh:
        fh.write(data)
    return stored


def resolve_path(stored_filename):
    """Return the absolute path of a stored resume, refusing anything outside UPLOAD_FOLDER."""
    folder = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    if not stored_filename or os.path.basename(stored_filename) != stored_filename:
        raise ResumeError("Invalid file reference.")
    path = os.path.realpath(os.path.join(folder, stored_filename))
    if not path.startswith(folder + os.sep):
        raise ResumeError("Invalid file reference.")
    return path


def delete_file(stored_filename):
    try:
        path = resolve_path(stored_filename)
        if os.path.exists(path):
            os.remove(path)
    except (ResumeError, OSError):
        log.warning("Could not delete resume file %s", stored_filename)


def extract_text(path):
    """Extract text from a PDF. Returns (text, status, message)."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return "", "error", "The PDF is password protected; please upload an unprotected copy."
        parts = []
        for page in reader.pages[:MAX_PAGES]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        log.info("PDF parse failure: %s", exc)
        return "", "error", "The PDF could not be read. Try exporting it again from your editor."
    if len(text) < 20:
        return "", "no_text", ("No selectable text found. Scanned/image-only PDFs are not supported "
                               "(no OCR); please upload a text-based PDF or add skills manually.")
    return text[:50000], "ok", f"Extracted text from {min(len(reader.pages), MAX_PAGES)} page(s)."


def process_pdf(path):
    """Return dict(text, status, message, skills)."""
    text, status, message = extract_text(path)
    skills = extract_skills(text) if text else []
    return {"text": text, "status": status, "message": message, "skills": skills}
