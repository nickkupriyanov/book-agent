#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
postgres_port=${POSTGRES_PORT:-5432}
database_url=${DATABASE_URL:-postgresql+psycopg://book_agent:book_agent@localhost:${postgres_port}/book_agent}

cd "$project_dir"
POSTGRES_PORT="$postgres_port" docker compose up -d --wait postgres

cd "$project_dir/backend"
DATABASE_URL="$database_url" uv run alembic upgrade head
DATABASE_URL="$database_url" uv run python -m app.seed
