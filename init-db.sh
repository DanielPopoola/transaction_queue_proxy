#!/bin/bash
set -e


echo "Creating test database..."


psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE ${POSTGRES_DB}_test' 
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_DB}_test')\gexec
EOSQL

echo "Test database ${POSTGRES_DB}_test created"

echo "Applying schema to test database..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${POSTGRES_DB}_test" < /docker-entrypoint-initdb.d/schema.sql

echo "Schema applied to both databases successfully"