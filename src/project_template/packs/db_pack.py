#!/usr/bin/env python3
"""Database add-on (`--with db`): SQLAlchemy 2.0 + Alembic + SQLite.

Purpose:
    Gives Python projects one consistent, layered way to use a database:
      - `src/<pkg>/adapters/db/` : ORM models, engine/session helpers, repositories
        (repositories return domain objects, so other layers never see ORM rows);
      - `alembic/` + `alembic.ini` : schema migrations (every table change gets a revision;
        `alembic check` fails when models and migrations differ);
      - SQLite file `<DATA_DIR>/db/app.db` (outside the project folder); switch to PostgreSQL
        by setting `DATABASE_URL` in `.env` only.
    Generated migration files use a template that already has docstrings.
"""

from __future__ import annotations

from pathlib import Path

from project_template.packs.common import write_file as _write

DB_DEPENDENCIES = ["sqlalchemy>=2.0", "alembic>=1.13"]
DB_CHECK = "uv run alembic upgrade head && uv run alembic check"

BASE_PY = '''"""Declarative base shared by every ORM model."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM models; `Base.metadata` is what Alembic compares against."""
'''

MODELS_PY = '''"""ORM models (database tables). Only the adapters layer imports these."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from {pkg}.adapters.db.base import Base


def utc_now() -> datetime:
    """Return the current time in UTC (default for timestamp columns).

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.now(timezone.utc)


class GreetingRecord(Base):
    """One stored greeting (table `greetings`).

    Attributes:
        id: Primary key.
        user_name: Name that was greeted.
        message: Greeting text.
        created_at: When the greeting was stored (UTC).
    """

    __tablename__ = "greetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_name: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
'''

SESSION_PY = '''"""Engine and session helpers: one place that knows how to connect and how to commit.

`session_scope()` commits when the block succeeds and rolls back on any error, so a
failed request never leaves half-written data.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite files the parent folder is created; `sqlite://` (in memory) uses one shared
    connection so tests and the API see the same data.

    Args:
        database_url: e.g. `sqlite:////Volumes/drive/projects-data/app/db/app.db` or `postgresql+psycopg://user@127.0.0.1/db`.

    Returns:
        The engine.
    """
    if database_url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(database_url, connect_args={{"check_same_thread": False}}, poolclass=StaticPool)
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(database_url, connect_args={{"check_same_thread": False}})
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the session factory used by repositories.

    Args:
        engine: Engine from `create_db_engine()`.

    Returns:
        A `sessionmaker` that does not expire objects on commit.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Open a session, commit on success, roll back on error, always close.

    Args:
        factory: Session factory from `make_session_factory()`.

    Yields:
        An open session.

    Raises:
        Exception: Any error from the block is re-raised after rollback.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
'''

REPOSITORY_PY = '''"""Greeting repository: stores and reads greetings, returning domain objects."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from {pkg}.adapters.db.models import GreetingRecord
from {pkg}.domain.models import GreetingResult


class GreetingRepository:
    """Database access for greetings (the only place that touches `GreetingRecord`)."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session.

        Args:
            session: Session from `session_scope()`.
        """
        self.session = session

    def add(self, user_name: str, result: GreetingResult) -> int:
        """Store one greeting.

        Args:
            user_name: Name that was greeted.
            result: Greeting produced by the service layer.

        Returns:
            The new row ID.
        """
        record = GreetingRecord(user_name=user_name, message=result.message)
        self.session.add(record)
        self.session.flush()
        return record.id

    def recent(self, limit: int = 20, environment: str = "") -> list[GreetingResult]:
        """Return the newest greetings first.

        Args:
            limit: Maximum number of rows.
            environment: Environment name copied into the returned domain objects.

        Returns:
            Greetings as domain objects.
        """
        stmt = select(GreetingRecord).order_by(GreetingRecord.id.desc()).limit(limit)
        rows = self.session.scalars(stmt)
        return [GreetingResult(message=r.message, environment=environment) for r in rows]
'''

DB_TEST = '''"""Tests for the database adapter (in-memory SQLite, no files left behind)."""

from __future__ import annotations

import unittest

from {pkg}.adapters.db.base import Base
from {pkg}.adapters.db.repository import GreetingRepository
from {pkg}.adapters.db.session import create_db_engine, make_session_factory, session_scope
from {pkg}.domain.models import GreetingResult


class GreetingRepositoryTest(unittest.TestCase):
    """Storing and reading greetings."""

    def setUp(self) -> None:
        """Create a fresh in-memory database with all tables."""
        engine = create_db_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.factory = make_session_factory(engine)

    def test_add_and_read_back(self) -> None:
        """A stored greeting comes back from `recent()`."""
        with session_scope(self.factory) as session:
            GreetingRepository(session).add("Ann", GreetingResult(message="Hello, Ann!", environment="test"))
        with session_scope(self.factory) as session:
            rows = GreetingRepository(session).recent(environment="test")
        self.assertEqual([r.message for r in rows], ["Hello, Ann!"])

    def test_error_rolls_back(self) -> None:
        """An exception inside `session_scope` leaves the database unchanged."""
        with self.assertRaises(RuntimeError), session_scope(self.factory) as session:
            GreetingRepository(session).add("Bob", GreetingResult(message="Hello, Bob!", environment="test"))
            raise RuntimeError("boom")
        with session_scope(self.factory) as session:
            self.assertEqual(GreetingRepository(session).recent(), [])


if __name__ == "__main__":
    unittest.main()
'''

ALEMBIC_INI = """# Alembic configuration. The database URL comes from DATABASE_URL (.env) via the config layer.
[alembic]
script_location = alembic
prepend_sys_path = src
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
"""

ENV_PY = '''"""Alembic environment: connects with the app's config and compares against the ORM models."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from {pkg}.adapters.db import models  # noqa: F401 - registers every table on Base.metadata
from {pkg}.adapters.db.base import Base
from {pkg}.adapters.db.session import create_db_engine
from {pkg}.config.settings import load_config

alembic_config = context.config
if alembic_config.config_file_name:
    fileConfig(alembic_config.config_file_name)
DATABASE_URL = load_config().database_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations (batch mode so SQLite can ALTER tables)."""
    with create_db_engine(DATABASE_URL).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''

SCRIPT_MAKO = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | None = ${repr(branch_labels)}
depends_on: str | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply this revision (describe the schema change here)."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert this revision."""
    ${downgrades if downgrades else "pass"}
'''

FIRST_REVISION = '''"""Create the greetings table.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create `greetings` (id, user_name, message, created_at)."""
    op.create_table(
        "greetings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_name", sa.String(length=100), nullable=False),
        sa.Column("message", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop `greetings`."""
    op.drop_table("greetings")
'''

DB_GUIDE = """# 資料庫（SQLAlchemy + Alembic + SQLite）

- 連線位置：預設是資料資料夾內的 `<DATA_DIR>/db/app.db`（`DATA_DIR` 在 `.env`，位於專案資料夾之外）；要用其他資料庫時，在 `.env` 設定 `DATABASE_URL`。
- 資料表定義：`src/<pkg>/adapters/db/models.py`；存取資料只透過 `repository.py`，回傳 domain 物件。
- 交易：一律用 `session_scope()`，成功自動 commit、錯誤自動 rollback。

改資料表的流程：

1. 修改 `models.py`。
2. 產生遷移檔（檔案開頭會有說明，請補上變更內容）：

```bash
uv run alembic revision --autogenerate -m "add price to products"
```

3. 套用到本機資料庫：

```bash
uv run alembic upgrade head
```

4. 確認模型和遷移一致（`agentctl check` 也會檢查）：

```bash
uv run alembic check
```

改用 PostgreSQL：`uv add 'psycopg[binary]'`，再把 `DATABASE_URL` 改成 `postgresql+psycopg://user@127.0.0.1:5432/dbname`。
"""


def scaffold_db_pack(target_dir: Path, pkg: str) -> None:
    """Create the database adapter, Alembic setup, first migration and tests.

    Args:
        target_dir: Project root directory.
        pkg: Python package name under `src/`.
    """
    db = target_dir / "src" / pkg / "adapters" / "db"
    _write(db / "__init__.py", '"""Database adapter: ORM models, sessions and repositories."""\n')
    _write(db / "base.py", BASE_PY)
    _write(db / "models.py", MODELS_PY.format(pkg=pkg))
    _write(db / "session.py", SESSION_PY.format())
    _write(db / "repository.py", REPOSITORY_PY.format(pkg=pkg))
    _write(target_dir / "alembic.ini", ALEMBIC_INI)
    _write(target_dir / "alembic" / "env.py", ENV_PY.format(pkg=pkg))
    _write(target_dir / "alembic" / "script.py.mako", SCRIPT_MAKO)
    _write(target_dir / "alembic" / "versions" / "20260101_0001_create_greetings.py", FIRST_REVISION)
    _write(target_dir / "alembic" / "DB.md", DB_GUIDE)
    _write(target_dir / "tests" / "test_db.py", DB_TEST.format(pkg=pkg))
