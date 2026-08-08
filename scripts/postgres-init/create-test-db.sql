-- The database `uv run pytest` truncates. Kept apart from `epyhia` so the suite can never
-- destroy a run of record. Runs only on a fresh volume; see TEST_DATABASE_URL in
-- .env.example for the one-liner that creates it on an existing one.
CREATE DATABASE epyhia_test;
