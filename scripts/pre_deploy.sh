#!/bin/sh
set -eu

echo "Pre-deploy: applying database migrations"
alembic upgrade head

echo "Pre-deploy: seeding superadmin"
python seed_superadmin.py

echo "Pre-deploy: seeding food catalog"
python seed_food_catalog.py

echo "Pre-deploy: complete"
