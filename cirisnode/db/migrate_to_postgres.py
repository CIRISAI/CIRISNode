import psycopg2
from psycopg2 import sql
import sqlite3

# SQLite and Postgres database configurations
SQLITE_DB_PATH = "cirisnode.db"
POSTGRES_CONFIG = {
    "dbname": "cirisnode",
    "user": "postgres",
    "password": "password",
    "host": "localhost",
    "port": 5432,
}

# Migration script
def migrate_sqlite_to_postgres():
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()

    # Connect to Postgres
    postgres_conn = psycopg2.connect(**POSTGRES_CONFIG)
    postgres_cursor = postgres_conn.cursor()

    # Define tables to migrate
    tables = ["jobs", "wbd_tasks", "audit", "agent_events", "agent_tokens"]

    for table in tables:
        # Fetch data from SQLite
        sqlite_cursor.execute(f"SELECT * FROM {table}")
        rows = sqlite_cursor.fetchall()

        # Get column names
        column_names = [desc[0] for desc in sqlite_cursor.description]

        # Insert data into Postgres
        for row in rows:
            insert_query = sql.SQL("INSERT INTO {table} ({columns}) VALUES ({values})").format(
                table=sql.Identifier(table),
                columns=sql.SQL(", ").join(map(sql.Identifier, column_names)),
                values=sql.SQL(", ").join(sql.Placeholder() * len(row))
            )
            postgres_cursor.execute(insert_query, row)

    # Commit and close connections
    postgres_conn.commit()
    sqlite_conn.close()
    postgres_conn.close()

if __name__ == "__main__":
    migrate_sqlite_to_postgres()
