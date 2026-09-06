"""m0_rational_time_rate

TIME_MODEL_UNIT_BLOCKER 修正：time_ratio_history 的模糊 float 倍率 ratio_value
替换为有量纲有理速率（INTEGER numerator + INTEGER denominator）。

- 单位：rate_numerator [blessed ticks] / rate_denominator [real µs]。
- 自然态（Bible WS-0201：现实约 1 天 ≈ 福地约 1 年）：
  1,000,000 ticks / 86,400,000,000 µs。
- 数据转换：仅自然态行（reason LIKE BIBLE_V1_WS-0201_NATURAL% 且 ratio_value=365.0）
  安全转换为自然态速率；存在其它无法审计转换的行 → 迁移失败（绝不静默错转）。
- 前序 ratio=365.0 是对 Canon"约 365 倍"的误读（把派生展示语当成了 365 福地年/天），
  World Seed 未激活、无历史数据，现在是最后修正窗口。

Revision ID: e9f4b7c2d8a6
Revises: b2d4e8f9a6c3
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f4b7c2d8a6'
down_revision: Union[str, Sequence[str], None] = 'b2d4e8f9a6c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NATURAL_NUM = 1_000_000          # blessed ticks（1 福地年）
NATURAL_DEN = 86_400_000_000     # real µs（1 现实天）


def upgrade() -> None:
    """ratio_value FLOAT → rate_numerator/rate_denominator BIGINT（审计安全转换）。"""
    with op.batch_alter_table("time_ratio_history") as b:
        b.add_column(sa.Column("rate_numerator", sa.BigInteger(), nullable=True))
        b.add_column(sa.Column("rate_denominator", sa.BigInteger(), nullable=True))

    op.execute(
        "UPDATE time_ratio_history "
        "SET rate_numerator = 1000000, rate_denominator = 86400000000 "
        "WHERE ratio_value = 365.0 AND reason LIKE 'BIBLE_V1_WS-0201_NATURAL%'")

    bind = op.get_bind()
    unconverted = bind.execute(sa.text(
        "SELECT ratio_id, reason, ratio_value FROM time_ratio_history "
        "WHERE rate_numerator IS NULL OR rate_denominator IS NULL"
    )).fetchall()
    if unconverted:
        raise NotImplementedError(
            f"存在无法审计转换的历史速率行（禁止静默错转）: {unconverted}")

    with op.batch_alter_table("time_ratio_history") as b:
        b.alter_column("rate_numerator", existing_type=sa.BigInteger(),
                       existing_nullable=True, nullable=False)
        b.alter_column("rate_denominator", existing_type=sa.BigInteger(),
                       existing_nullable=True, nullable=False)
        b.drop_column("ratio_value")


def downgrade() -> None:
    with op.batch_alter_table("time_ratio_history") as b:
        b.add_column(sa.Column("ratio_value", sa.Float(), nullable=True))
    op.execute(
        "UPDATE time_ratio_history SET ratio_value = 365.0 "
        "WHERE rate_numerator = 1000000 AND rate_denominator = 86400000000")
    with op.batch_alter_table("time_ratio_history") as b:
        b.alter_column("ratio_value", existing_type=sa.Float(),
                       existing_nullable=True, nullable=False)
        b.drop_column("rate_numerator")
        b.drop_column("rate_denominator")
