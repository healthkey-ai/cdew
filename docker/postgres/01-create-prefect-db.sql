-- Runs once, on first init of the postgres_data volume. The Prefect server keeps
-- its state here (SQLite locks under the classify/extract task fan-out).
CREATE DATABASE prefect OWNER cdew;
