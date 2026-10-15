from flask import request, url_for
from markupsafe import Markup, escape
from flask_login import current_user

STATUS_STYLES = {
    # applications
    "submitted": ("secondary", "Submitted"),
    "shortlisted": ("info", "Shortlisted"),
    "selected": ("primary", "Selected"),
    "rejected": ("danger", "Rejected"),
    "allocated": ("success", "Allocated"),
    "withdrawn": ("dark", "Withdrawn"),
    # internships
    "draft": ("secondary", "Draft"),
    "published": ("success", "Published"),
    "closed": ("dark", "Closed"),
    # allocations / runs
    "proposed": ("warning", "Proposed"),
    "active": ("success", "Active"),
    "cancelled": ("danger", "Cancelled"),
    "discarded": ("secondary", "Discarded"),
    "preview": ("warning", "Preview"),
    "confirmed": ("success", "Confirmed"),
    "failed": ("danger", "Failed"),
}

NAV = {
    "student": [
        ("student.dashboard", "bi-grid-1x2", "Dashboard"),
        ("student.profile", "bi-person-badge", "My Profile"),
        ("student.recommendations", "bi-stars", "Recommendations"),
        ("student.internships", "bi-briefcase", "Browse Internships"),
        ("student.applications", "bi-send-check", "My Applications"),
        ("student.allocations", "bi-award", "Allocation & Feedback"),
        ("main.notifications", "bi-bell", "Notifications"),
    ],
    "company": [
        ("company.dashboard", "bi-grid-1x2", "Dashboard"),
        ("company.profile", "bi-building", "Company Profile"),
        ("company.internships", "bi-briefcase", "Internships"),
        ("company.allocations", "bi-people", "Assigned Candidates"),
        ("main.notifications", "bi-bell", "Notifications"),
    ],
    "admin": [
        ("admin.dashboard", "bi-speedometer2", "Dashboard"),
        ("admin.students", "bi-mortarboard", "Students"),
        ("admin.companies", "bi-buildings", "Companies"),
        ("admin.internships", "bi-briefcase", "Internships"),
        ("admin.applications", "bi-inboxes", "Applications"),
        ("admin.allocation", "bi-diagram-3", "Allocation"),
        ("admin.reports", "bi-file-earmark-bar-graph", "Reports"),
        ("admin.feedback", "bi-chat-square-heart", "Feedback"),
        ("admin.announcements", "bi-megaphone", "Announcements"),
        ("admin.settings", "bi-sliders", "Settings"),
        ("admin.audit", "bi-shield-check", "Audit Log"),
        ("main.notifications", "bi-bell", "Notifications"),
    ],
}


ACTIVE_ALIASES = {
    "student.internship_detail": "student.internships",
    "company.new_internship": "company.internships", "company.edit_internship": "company.internships",
    "company.applicants": "company.internships", "company.application_detail": "company.internships",
    "admin.student_detail": "admin.students", "admin.new_company": "admin.companies",
    "admin.edit_company": "admin.companies", "admin.new_internship": "admin.internships",
    "admin.edit_internship": "admin.internships", "admin.applicants": "admin.internships",
    "admin.application_detail": "admin.applications", "admin.run_detail": "admin.allocation",
}


def register_template_helpers(app):
    @app.template_filter("dt")
    def fmt_dt(value, fmt="%d %b %Y, %H:%M"):
        return value.strftime(fmt) + (" UTC" if "%H" in fmt else "") if value else "—"

    @app.template_filter("d")
    def fmt_d(value):
        return value.strftime("%d %b %Y") if value else "—"

    @app.template_filter("inr")
    def fmt_inr(value):
        if value in (None, ""):
            return "Unpaid"
        return "₹{:,}/mo".format(int(value))

    @app.template_filter("score_class")
    def score_class(value):
        v = value or 0
        return "score-high" if v >= 70 else "score-mid" if v >= 45 else "score-low"

    @app.context_processor
    def inject():
        nav = NAV.get(current_user.role, []) if current_user.is_authenticated else []
        unread = current_user.unread_count() if current_user.is_authenticated else 0

        def status_badge(status):
            style, label = STATUS_STYLES.get(status, ("secondary", (status or "").title()))
            return Markup(f'<span class="badge rounded-pill status-badge text-bg-{style}">{escape(label)}</span>')

        def page_url(page):
            args = request.args.to_dict()
            args["page"] = page
            return url_for(request.endpoint, **(request.view_args or {}), **args)

        active = ACTIVE_ALIASES.get(request.endpoint, request.endpoint)
        return {"active_endpoint": active, "nav_items": nav, "unread_count": unread, "status_badge": status_badge, "page_url": page_url}
