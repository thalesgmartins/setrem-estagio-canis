"""Add animal photos table and stock item image column.

Revision ID: 0002_add_photos_tables
Revises: 0001_initial_schema
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_photos_tables"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create animal_fotos table and add image_filename to itens_estoque."""
    op.create_table(
        "animal_fotos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("animal_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["animal_id"], ["animais.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_animal_fotos_animal_id", "animal_fotos", ["animal_id"])
    op.add_column(
        "itens_estoque",
        sa.Column("image_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Drop animal_fotos table and remove image_filename from itens_estoque."""
    op.drop_column("itens_estoque", "image_filename")
    op.drop_index("ix_animal_fotos_animal_id", table_name="animal_fotos")
    op.drop_table("animal_fotos")
