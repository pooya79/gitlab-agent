"""Accessors for the singleton `app_settings` document.

These settings are runtime-editable via the /admin panel and persist across
restarts (the collection is seeded once in `init_db`, never reset).
"""

from __future__ import annotations

from pymongo.database import Database

from app.db.models import AppSettings


def get_app_settings(db: Database) -> AppSettings:
    """Return the singleton AppSettings document (creating an empty one if absent)."""
    doc = db["app_settings"].find_one({})
    settings_obj = AppSettings.from_document(doc)
    if settings_obj is None:
        settings_obj = AppSettings()
        db["app_settings"].insert_one(settings_obj.to_document())
    return settings_obj


def update_gitlab_settings(db: Database, **fields) -> AppSettings:
    """Update only the provided GitLab fields on the singleton document."""
    current = get_app_settings(db)
    update_doc = {k: v for k, v in fields.items() if v is not None}
    if update_doc:
        db["app_settings"].update_one({"_id": current._id}, {"$set": update_doc})
    return get_app_settings(db)


def is_gitlab_configured(db: Database) -> bool:
    """True when the GitLab OAuth credentials are all set."""
    s = get_app_settings(db)
    return bool(s.gitlab_base and s.gitlab_client_id and s.gitlab_client_secret)
