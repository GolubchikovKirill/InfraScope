#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding initial data..."
python -m app.initial_data

echo "Prestart complete."
