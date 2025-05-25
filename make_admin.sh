#!/bin/bash

# Script to make a user an admin in the CIRISNode application

echo "INFO: This script uses 'docker-compose' (with a hyphen)."
echo "INFO: Ensure your Docker services (especially 'db') are running: docker-compose ps"
echo ""

# --- Step 1: Apply Database Schema ---
echo "STEP 1: Attempting to apply database schema (cirisnode/db/schema.sql)..."
echo "If this step fails with a TTY error, you might need to run it manually or adjust docker-compose exec flags."

# Try with -T first for schema application, as psql can be interactive
# If docker-compose exec -T fails, it might be an old version.
# The user can then try: cat cirisnode/db/schema.sql | docker-compose exec db psql -U postgres -d cirisnode
docker-compose exec -T db psql -U postgres -d cirisnode < cirisnode/db/schema.sql
SCHEMA_EXIT_CODE=$?

if [ $SCHEMA_EXIT_CODE -ne 0 ]; then
  echo "WARNING: Applying schema with 'docker-compose exec -T ... < file' failed (exit code $SCHEMA_EXIT_CODE)."
  echo "This might be due to an older docker-compose version or TTY issues."
  echo "Attempting schema application by piping 'cat' to 'docker-compose exec db psql ...' (this often works better with older docker-compose versions for input redirection)."
  cat cirisnode/db/schema.sql | docker-compose exec db psql -U postgres -d cirisnode
  SCHEMA_EXIT_CODE=$?
  if [ $SCHEMA_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Applying schema failed with both methods. Please check errors above."
    echo "Ensure the 'db' service is running and accessible."
    echo "You may need to apply the schema manually."
    exit 1
  else
    echo "INFO: Schema applied successfully using 'cat ... | docker-compose exec ...'."
  fi
else
  echo "INFO: Schema applied successfully using 'docker-compose exec -T ... < file'."
fi
echo ""

# --- Step 2: Insert/Update Admin User ---
# Prompt for user details
read -p "Enter the Google email address of the user: " USER_EMAIL
read -p "Enter the Google User ID (oauth_sub) for this user: " OAUTH_SUB

# Validate inputs
if [ -z "$USER_EMAIL" ] || [ -z "$OAUTH_SUB" ]; then
  echo "Error: Email and OAuth User ID cannot be empty."
  exit 1
fi

echo ""
echo "STEP 2: Attempting to make '$USER_EMAIL' an admin..."

SQL_COMMAND="INSERT INTO users (username, role, groups, oauth_provider, oauth_sub) VALUES ('$USER_EMAIL', 'admin', 'admin', 'google', '$OAUTH_SUB') ON CONFLICT (username) DO UPDATE SET role = EXCLUDED.role, groups = EXCLUDED.groups, oauth_provider = EXCLUDED.oauth_provider, oauth_sub = EXCLUDED.oauth_sub;"

echo "Executing SQL: $SQL_COMMAND"
# Pass SQL_COMMAND as an argument to sh -c to handle quotes correctly
docker-compose exec db sh -c 'psql -U postgres -d cirisnode -c "$1"' -- "$SQL_COMMAND"
USER_UPDATE_EXIT_CODE=$?

if [ $USER_UPDATE_EXIT_CODE -eq 0 ]; then
  echo "INFO: SQL command for user update executed successfully (check psql output for INSERT/UPDATE count)."
  echo "'$USER_EMAIL' should now have admin privileges."
  echo ""
  echo "STEP 3: Please restart the api, ui, and worker services for changes to fully take effect:"
  echo "docker-compose restart api ui worker"
else
  echo "ERROR: SQL command for user update failed (exit code $USER_UPDATE_EXIT_CODE)."
  echo "Please check the psql output above and the database logs."
  echo "This usually means the 'users' table still doesn't exist (schema issue) or there was a problem with the SQL syntax/data."
fi
