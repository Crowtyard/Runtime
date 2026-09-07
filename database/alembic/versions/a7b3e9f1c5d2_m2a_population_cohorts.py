"""m2a_population_cohorts

M2a Population Group Engine schema：
population_groups 增加 age_advance_carry_ticks（亚年区间进位，整数）/ 
species_profile_ref（种族人口学 profile 引用；正式种族保持 NULL=UNCONFIGURED）/ 
demography_version（人口引擎语义版本）。

cohort 采用原设计（06 号）：cohort = population_groups 行
（species × settlement × age_cohort），age_cohort 存 bucket 序号字符串；
零 JSON、跨方言安全（PG 兼容）。

Revision ID: a7b3e9f1c5d2
Revises: e6c0f4a1b3d9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b3e9f1c5d2"
down_revision: Union[str, Sequence[str], None] = "e6c0f4a1b3d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("population_groups") as b:
        b.add_column(sa.Column("age_advance_carry_ticks", sa.BigInteger(),
                               nullable=False, server_default="0"))
        b.add_column(sa.Column("species_profile_ref", sa.String(64),
                               nullable=True))
        b.add_column(sa.Column("demography_version", sa.String(32),
                               nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("population_groups") as b:
        b.drop_column("demography_version")
        b.drop_column("species_profile_ref")
        b.drop_column("age_advance_carry_ticks")
