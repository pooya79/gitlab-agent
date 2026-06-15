"""MongoDB client helpers and lifecycle management."""

from __future__ import annotations

import datetime as dt
import logging

from pymongo import MongoClient, ReturnDocument
from pymongo.database import Database

from app.core.config import settings
from app.db.models import AppSettings, Configs

_client: MongoClient | None = None

logging.getLogger("pymongo").setLevel(logging.WARNING)


def get_client() -> MongoClient:
    """Return a shared MongoDB client instance."""

    global _client

    if _client is None:
        mongodb = settings.mongodb
        if mongodb.root_username and mongodb.root_password:
            uri = f"mongodb://{mongodb.root_username}:{mongodb.root_password}@{mongodb.host}:{mongodb.port}/{mongodb.database}?authSource=admin"
        else:
            uri = f"mongodb://{mongodb.host}:{mongodb.port}/{mongodb.database}"

        _client = MongoClient(uri, tz_aware=True, tzinfo=dt.timezone.utc)
    return _client


def close_client() -> None:
    """Cleanly close the MongoDB client if it has been created."""

    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_mongo_database() -> Database:
    """Retrieve the configured MongoDB database."""

    return get_client()[settings.mongodb.database]


def init_db() -> None:
    """Create required indexes for the application collections."""

    db = get_mongo_database()
    db["users"].create_index("email", unique=True)
    db["users"].create_index("username", unique=True, sparse=True)
    db["bots"].create_index("gitlab_project_path", unique=True)
    db["oauth_accounts"].create_index([("user_id", 1), ("provider", 1)], unique=True)
    db["refresh_sessions"].create_index("jti", unique=True)
    db["refresh_sessions"].create_index("expires_at", expireAfterSeconds=0, sparse=True)
    db["cache"].create_index("key", unique=True)
    db["cache"].create_index(
        "expires_at",
        expireAfterSeconds=0,
        partialFilterExpression={"expires_at": {"$exists": True}},
    )
    # Reset configs collection and insert default config
    configs_collection = db["configs"]
    configs_collection.delete_many({})

    default_configs = Configs()
    configs_collection.insert_one(default_configs.to_document())

    # Seed app_settings ONCE (DB is authoritative thereafter — see /admin panel).
    # Unlike configs, this is never wiped, so admin-edited values persist.
    app_settings_collection = db["app_settings"]
    if app_settings_collection.find_one({}) is None:
        seeded = AppSettings(
            gitlab_base=settings.gitlab.base,
            gitlab_client_id=settings.gitlab.client_id,
            gitlab_client_secret=settings.gitlab.client_secret,
            gitlab_webhook_ssl_verify=settings.gitlab.webhook_ssl_verify,
        )
        app_settings_collection.insert_one(seeded.to_document())


def get_next_sequence(collection_name: str) -> int:
    """
    Returns the next readable integer ID for a given collection.
    Safe for multiprocessing and concurrent workers.
    """
    db = get_mongo_database()
    counters = db["counters"]

    doc = counters.find_one_and_update(
        {"_id": collection_name},  # one counter per collection
        {"$inc": {"seq": 1}},  # atomic increment
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    return int(doc["seq"])
