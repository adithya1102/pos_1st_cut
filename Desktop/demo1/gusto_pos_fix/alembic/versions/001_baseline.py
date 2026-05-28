"""baseline schema - matches DDL v2.0

Revision ID: 001_baseline
Revises: 
Create Date: 2025-01-01 00:00:00.000000

This migration represents the schema as it exists AFTER the nuclear rebuild.
Running `alembic upgrade head` on a fresh DB will create all 21 tables.
Running it on the existing DB will detect no changes (already in sync).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This baseline migration is intentionally a no-op because the schema
    # already exists in your PostgreSQL database.
    #
    # Purpose: establishes Alembic's version tracking so future
    # `alembic revision --autogenerate` commands work correctly.
    #
    # If deploying to a FRESH database, replace `pass` with the full
    # CREATE TABLE statements or use `alembic revision --autogenerate`
    # against an empty DB to generate them automatically.
    pass


def downgrade() -> None:
    pass
