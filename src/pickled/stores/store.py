from enum import StrEnum

from sqlalchemy import Enum


class Store(StrEnum):
    AH = "ah"
    JUMBO = "jumbo"


# The Postgres `store` enum, shared by every table with a store column.
STORE_TYPE = Enum(Store, name="store", values_callable=lambda store: [s.value for s in store])
