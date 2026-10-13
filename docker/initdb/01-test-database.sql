-- Runs once, when the volume is first created. pg_trgm itself is enabled by the
-- first Alembic migration, so both databases get it.
CREATE DATABASE pickled_test OWNER pickled;
