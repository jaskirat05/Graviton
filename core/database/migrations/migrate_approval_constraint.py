"""
Database migration: Remove UNIQUE constraint from approval_requests.temporal_workflow_id

This allows multiple steps in the same workflow to have separate approval requests.
"""

import sqlite3
from pathlib import Path

def migrate():
    # Database is in core/data/artifacts.db
    db_path = Path(__file__).parent.parent / "data" / "artifacts.db"

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting migration: Remove UNIQUE constraint from temporal_workflow_id")

        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='approval_requests'")
        if not cursor.fetchone():
            print("Table 'approval_requests' not found, skipping migration")
            return

        # SQLite doesn't support dropping constraints, so we recreate the table
        print("Step 1: Creating new table without UNIQUE constraint...")

        cursor.execute("""
            CREATE TABLE approval_requests_new (
                id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                chain_id TEXT,
                step_id TEXT,
                temporal_workflow_id TEXT NOT NULL,
                temporal_run_id TEXT,
                approval_link_token TEXT UNIQUE NOT NULL,
                artifact_view_url TEXT NOT NULL,
                link_expires_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'pending',
                decided_at TIMESTAMP,
                decided_by TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config_metadata TEXT,
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
                FOREIGN KEY(chain_id) REFERENCES chains(id) ON DELETE CASCADE
            )
        """)

        print("Step 2: Copying data from old table...")
        cursor.execute("""
            INSERT INTO approval_requests_new
            SELECT * FROM approval_requests
        """)

        print("Step 3: Dropping old table...")
        cursor.execute("DROP TABLE approval_requests")

        print("Step 4: Renaming new table...")
        cursor.execute("ALTER TABLE approval_requests_new RENAME TO approval_requests")

        print("Step 5: Creating indexes...")
        cursor.execute("CREATE INDEX idx_approval_requests_artifact ON approval_requests(artifact_id)")
        cursor.execute("CREATE INDEX idx_approval_requests_chain ON approval_requests(chain_id)")
        cursor.execute("CREATE INDEX idx_approval_requests_status ON approval_requests(status)")
        cursor.execute("CREATE INDEX idx_approval_requests_temporal ON approval_requests(temporal_workflow_id)")
        cursor.execute("CREATE INDEX idx_approval_requests_link_token ON approval_requests(approval_link_token)")

        conn.commit()
        print("✓ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"✗ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
