#!/bin/bash
set -e

# Create the comfyautomate database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE comfyautomate;
    GRANT ALL PRIVILEGES ON DATABASE comfyautomate TO temporal;
EOSQL
