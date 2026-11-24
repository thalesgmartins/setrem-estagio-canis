"""Create initial Canis relational schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create core Canis tables."""
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("senha_hash", sa.String(length=255), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("tema", sa.String(length=20), nullable=False, server_default="dark"),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_sub"),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"])
    op.create_index("ix_usuarios_role", "usuarios", ["role"])

    op.create_table(
        "animais",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("species", sa.String(length=40), nullable=False),
        sa.Column("breed", sa.String(length=120), nullable=False),
        sa.Column("size", sa.String(length=60), nullable=False),
        sa.Column("age_approx", sa.String(length=60), nullable=False),
        sa.Column("gender", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("intake_date", sa.String(length=20), nullable=False),
        sa.Column("neutered", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("microchip", sa.String(length=60), nullable=False),
        sa.Column("rescue_notes", sa.Text(), nullable=False),
        sa.Column("temperament", sa.String(length=255), nullable=False),
        sa.Column("foster_history_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_animais_name", "animais", ["name"])
    op.create_index("ix_animais_status", "animais", ["status"])

    op.create_table(
        "vacinas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("animal_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("date_applied", sa.String(length=20), nullable=False),
        sa.Column("next_due_date", sa.String(length=20), nullable=False),
        sa.Column("lot", sa.String(length=60), nullable=False),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["animal_id"], ["animais.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "eventos_clinicos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("animal_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("veterinarian", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["animal_id"], ["animais.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "itens_estoque",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("lot_number", sa.String(length=60), nullable=False),
        sa.Column("expiration_date", sa.String(length=20), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lares_temporarios",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("volunteer_name", sa.String(length=150), nullable=False),
        sa.Column("contact", sa.String(length=60), nullable=False),
        sa.Column("neighborhood", sa.String(length=120), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("active_animals_csv", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "termos_adocao",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("adopter_name", sa.String(length=180), nullable=False),
        sa.Column("adopter_cpf", sa.String(length=20), nullable=False),
        sa.Column("adopter_contact", sa.String(length=60), nullable=False),
        sa.Column("adopter_address", sa.String(length=255), nullable=False),
        sa.Column("animal_name", sa.String(length=120), nullable=False),
        sa.Column("animal_species", sa.String(length=40), nullable=False),
        sa.Column("adoption_date", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lancamentos_financeiros",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tx_date", sa.String(length=20), nullable=False),
        sa.Column("tx_type", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("payment_method", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("related_animal", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fin_tx_type", "lancamentos_financeiros", ["tx_type"])
    op.create_index("ix_fin_status", "lancamentos_financeiros", ["status"])


def downgrade() -> None:
    """Drop all Canis tables."""
    op.drop_table("lancamentos_financeiros")
    op.drop_table("termos_adocao")
    op.drop_table("lares_temporarios")
    op.drop_table("itens_estoque")
    op.drop_table("eventos_clinicos")
    op.drop_table("vacinas")
    op.drop_table("animais")
    op.drop_table("usuarios")
