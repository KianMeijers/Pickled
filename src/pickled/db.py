"""SQLAlchemy base and the data model conventions every module's tables follow.

- `bigint` identity keys (`id: Mapped[IdPk]`).
- Money in integer cents, so plain `int` maps to `bigint`.
- `timestamptz` for timestamps, `date` for days, `numeric` for quantities.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase, mapped_column

IdPk = Annotated[int, mapped_column(BigInteger, Identity(), primary_key=True)]

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        int: BigInteger,
        datetime: DateTime(timezone=True),
        Decimal: Numeric,
    }
