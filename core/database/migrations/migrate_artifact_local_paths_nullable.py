"""
Migration: Make artifacts.local_filename and artifacts.local_path nullable.

This supports remote-only artifacts that only store asset metadata.
"""

import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent.parent / "data" / "artifacts.db"


def migrate() -> None:
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'")
        if not cursor.fetchone():
            print("Table 'artifacts' not found, skipping migration")
            return

        cursor.execute("PRAGMA table_info(artifacts)")
        columns = {row[1]: row for row in cursor.fetchall()}
        local_filename_notnull = int(columns.get("local_filename", [None, None, None, 1])[3]) == 1
        local_path_notnull = int(columns.get("local_path", [None, None, None, 1])[3]) == 1
        if not local_filename_notnull and not local_path_notnull:
            print("Artifacts local path columns already nullable; nothing to migrate")
            return

        print("Migrating artifacts table to nullable local_filename/local_path...")
        cursor.execute("PRAGMA foreign_keys=OFF")

        cursor.execute(
            """
            CREATE TABLE artifacts_new (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                local_filename TEXT UNIQUE,
                local_path TEXT UNIQUE,
                file_type TEXT NOT NULL,
                file_format TEXT,
                file_size INTEGER,
                node_id TEXT,
                subfolder TEXT DEFAULT '',
                comfy_folder_type TEXT DEFAULT 'output',
                version INTEGER DEFAULT 1,
                is_latest BOOLEAN DEFAULT 1,
                parent_artifact_id TEXT,
                approval_status TEXT DEFAULT 'auto_approved',
                approved_by TEXT,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                extra_metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
            )
            """
        )

        cursor.execute(
            """
            INSERT INTO artifacts_new (
                id, workflow_id, filename, local_filename, local_path, file_type, file_format,
                file_size, node_id, subfolder, comfy_folder_type, version, is_latest,
                parent_artifact_id, approval_status, approved_by, approved_at, rejection_reason,
                extra_metadata, created_at, updated_at
            )
            SELECT
                id, workflow_id, filename, local_filename, local_path, file_type, file_format,
                file_size, node_id, subfolder, comfy_folder_type, version, is_latest,
                parent_artifact_id, approval_status, approved_by, approved_at, rejection_reason,
                extra_metadata, created_at, updated_at
            FROM artifacts
            """
        )

        cursor.execute("DROP TABLE artifacts")
        cursor.execute("ALTER TABLE artifacts_new RENAME TO artifacts")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_workflow ON artifacts(workflow_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_latest ON artifacts(workflow_id, is_latest)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_approval ON artifacts(approval_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at)")

        cursor.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        print("✓ Migration complete")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Database: {DATABASE_PATH}")
    print(f"Exists: {DATABASE_PATH.exists()}")
    if not DATABASE_PATH.exists():
        raise SystemExit("Database does not exist")
    migrate()
