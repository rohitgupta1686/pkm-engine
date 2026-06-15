import pathlib

import libsql_experimental as libsql

from pkm.config import Settings


def get_migrations_dir() -> pathlib.Path:
    """Return the path to the migrations/sqlite directory."""
    return pathlib.Path(__file__).parent.parent.parent / "migrations" / "sqlite"


def _run_migrations(conn) -> None:
    """Execute both migration files in order. IF NOT EXISTS guards make this idempotent."""
    migrations_dir = get_migrations_dir()
    for filename in ("001_init.sql", "002_graph_tables.sql"):
        migration_path = migrations_dir / filename
        sql = migration_path.read_text()
        conn.executescript(sql)


def connect(settings: Settings | None = None):
    """
    Return a libsql connection with auto-migration applied.

    If settings is None, the module-level singleton from pkm.config is used.
    If settings.turso_url is truthy, connects to Turso cloud with auth_token.
    Otherwise opens a local SQLite file at settings.db_path.
    """
    if settings is None:
        from pkm.config import settings as _settings
        settings = _settings

    if settings.turso_url:
        conn = libsql.connect(database=settings.turso_url, auth_token=settings.turso_token)
    else:
        conn = libsql.connect(settings.db_path)

    _run_migrations(conn)
    return conn
