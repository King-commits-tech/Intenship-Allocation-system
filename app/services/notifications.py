"""In-app notifications stored in the database.

Delivery is not real-time push: the UI polls the unread count every 60 seconds
and shows notifications on page load.
"""
from app.extensions import db
from app.models import Notification, Role, User


def notify(user, title, message, category="info", link=None):
    if user is None:
        return None
    n = Notification(user_id=user.id, title=title[:150], message=message, category=category, link=link)
    db.session.add(n)
    return n


def notify_role(audience, title, message, category="announcement", link=None):
    """Notify all active users of a role ('student', 'company') or everyone ('all')."""
    q = User.query.filter(User.is_active_flag.is_(True))
    if audience in (Role.STUDENT, Role.COMPANY):
        q = q.filter(User.role == audience)
    else:
        q = q.filter(User.role.in_([Role.STUDENT, Role.COMPANY]))
    count = 0
    for user in q.all():
        notify(user, title, message, category, link)
        count += 1
    return count
