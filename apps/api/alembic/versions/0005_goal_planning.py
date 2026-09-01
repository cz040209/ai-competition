"""versioned deterministic goal planning

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "goals",
        sa.Column("goal_type", sa.String(length=40), server_default="custom_goal", nullable=False),
    )
    op.add_column(
        "goals", sa.Column("currency", sa.String(length=3), server_default="MYR", nullable=False)
    )
    # goals.target_date already arrived with 0003; the planner only needs it
    # indexed. Legacy goals keep it null and stay readable by the old dashboard.
    op.add_column(
        "goals",
        sa.Column("priority", sa.String(length=12), server_default="flexible", nullable=False),
    )
    op.add_column(
        "goals", sa.Column("status", sa.String(length=16), server_default="active", nullable=False)
    )
    op.add_column(
        "goals", sa.Column("funding_account_ids", sa.JSON(), server_default="[]", nullable=False)
    )
    op.add_column(
        "goals",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "goals",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_goals_goal_type", "goals", ["goal_type"])
    op.create_index("ix_goals_target_date", "goals", ["target_date"])
    op.create_index("ix_goals_priority", "goals", ["priority"])
    op.create_index("ix_goals_status", "goals", ["status"])

    op.create_table(
        "goal_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(length=12), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("target_amount", sa.BigInteger(), nullable=False),
        sa.Column("current_saved", sa.BigInteger(), nullable=False),
        sa.Column("remaining_amount", sa.BigInteger(), nullable=False),
        sa.Column("required_contribution_per_payday", sa.BigInteger(), nullable=False),
        sa.Column("next_required_reserve", sa.BigInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("projected_completion_date", sa.Date(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name="fk_goal_plans_goal_id_goals", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goal_plans"),
        sa.UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),
    )
    op.create_index("ix_goal_plans_goal_id", "goal_plans", ["goal_id"])
    op.create_index("ix_goal_plans_approval_status", "goal_plans", ["approval_status"])

    op.create_table(
        "goal_scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("contribution_per_payday", sa.BigInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("goal_delay_days", sa.Integer(), nullable=False),
        sa.Column("flexible_spending_delta", sa.BigInteger(), nullable=False),
        sa.Column("tradeoffs", sa.JSON(), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["goal_plans.id"],
            name="fk_goal_scenarios_plan_id_goal_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goal_scenarios"),
    )
    op.create_index("ix_goal_scenarios_plan_id", "goal_scenarios", ["plan_id"])

    op.create_table(
        "goal_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("percentage", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("projected_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["goal_plans.id"],
            name="fk_goal_milestones_plan_id_goal_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goal_milestones"),
        sa.UniqueConstraint("plan_id", "percentage", name="uq_goal_milestones_plan_percentage"),
    )
    op.create_index("ix_goal_milestones_plan_id", "goal_milestones", ["plan_id"])


def downgrade() -> None:
    op.drop_table("goal_milestones")
    op.drop_table("goal_scenarios")
    op.drop_table("goal_plans")
    op.drop_index("ix_goals_status", table_name="goals")
    op.drop_index("ix_goals_priority", table_name="goals")
    op.drop_index("ix_goals_target_date", table_name="goals")
    op.drop_index("ix_goals_goal_type", table_name="goals")
    for column in (
        "updated_at",
        "created_at",
        "funding_account_ids",
        "status",
        "priority",
        "currency",
        "goal_type",
    ):
        op.drop_column("goals", column)
