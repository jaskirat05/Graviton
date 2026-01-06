"""
Migration: Add version and regenerated_from_step_id to Chain table

Run this script to add versioning support to existing database.
"""

import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent.parent / "data" / "artifacts.db"


def migrate():
    """Add version columns to Chain table"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    print("Checking current Chain table schema...")
    cursor.execute("PRAGMA table_info(chains)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"Existing columns: {columns}")

    # Add version column
    if 'version' not in columns:
        print("Adding 'version' column...")
        cursor.execute("""
            ALTER TABLE chains
            ADD COLUMN version INTEGER NOT NULL DEFAULT 1
        """)
        print("✓ Added 'version' column")
    else:
        print("✓ 'version' column already exists")

    # Add regenerated_from_step_id column
    if 'regenerated_from_step_id' not in columns:
        print("Adding 'regenerated_from_step_id' column...")
        cursor.execute("""
            ALTER TABLE chains
            ADD COLUMN regenerated_from_step_id TEXT
        """)
        print("✓ Added 'regenerated_from_step_id' column")
    else:
        print("✓ 'regenerated_from_step_id' column already exists")

    # Commit changes
    conn.commit()

    # Create unique index for (name, version)
    print("Creating unique index on (name, version)...")
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chain_name_version
            ON chains(name, version)
        """)
        print("✓ Created unique index")
    except sqlite3.IntegrityError as e:
        print(f"⚠ Index creation failed (may already exist): {e}")

    # Create composite index for queries
    print("Creating composite index on (name, status, version)...")
    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chains_name_status_version
            ON chains(name, status, version)
        """)
        print("✓ Created composite index")
    except Exception as e:
        print(f"⚠ Index creation failed: {e}")

    conn.commit()
    conn.close()

    print("\n✅ Migration complete!")
    print("\nNew Chain table schema:")
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(chains)")
    for row in cursor.fetchall():
        print(f"  {row[1]}: {row[2]}")
    conn.close()


if __name__ == "__main__":
    print(f"Database: {DATABASE_PATH}")
    print(f"Exists: {DATABASE_PATH.exists()}")
    print()

    if not DATABASE_PATH.exists():
        print("❌ Database does not exist! Run init_db() first.")
        exit(1)

    migrate()
