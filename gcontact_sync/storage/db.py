"""
SQLite database module for sync state management.

Provides persistent storage for sync tokens, contact mappings, and sync state.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple


# SQL Schema for sync state and contact mapping tables
SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    sync_token TEXT,
    last_sync_at TIMESTAMP,
    UNIQUE(account_id)
);

CREATE TABLE IF NOT EXISTS contact_mapping (
    id INTEGER PRIMARY KEY,
    matching_key TEXT NOT NULL,
    account1_resource_name TEXT,
    account2_resource_name TEXT,
    account1_etag TEXT,
    account2_etag TEXT,
    last_synced_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(matching_key)
);

CREATE INDEX IF NOT EXISTS idx_contact_mapping_key ON contact_mapping(matching_key);
CREATE INDEX IF NOT EXISTS idx_sync_state_account ON sync_state(account_id);
"""


class SyncDatabase:
    """
    SQLite database manager for sync state and contact mappings.

    Provides methods for:
    - Managing sync tokens per account
    - Tracking contact mappings between accounts
    - Storing content hashes for change detection

    Usage:
        db = SyncDatabase('/path/to/sync.db')
        db.initialize()

        # Or use in-memory for testing:
        db = SyncDatabase(':memory:')
        db.initialize()
    """

    def __init__(self, db_path: str):
        """
        Initialize the database manager.

        Args:
            db_path: Path to SQLite database file, or ':memory:' for in-memory database
        """
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection

        Usage:
            with db.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sync_state")
        """
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """
        Initialize the database schema.

        Creates the sync_state and contact_mapping tables if they don't exist.
        """
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    # =========================================================================
    # Sync State Operations
    # =========================================================================

    def get_sync_state(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Get sync state for an account.

        Args:
            account_id: The account identifier (e.g., 'account1', 'account2')

        Returns:
            Dictionary with sync_token and last_sync_at, or None if not found
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT sync_token, last_sync_at FROM sync_state WHERE account_id = ?",
                (account_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'sync_token': row['sync_token'],
                    'last_sync_at': row['last_sync_at']
                }
            return None

    def update_sync_state(
        self,
        account_id: str,
        sync_token: Optional[str] = None,
        last_sync_at: Optional[datetime] = None
    ) -> None:
        """
        Update or insert sync state for an account.

        Args:
            account_id: The account identifier
            sync_token: The Google API sync token (optional)
            last_sync_at: Timestamp of last sync (defaults to current time)
        """
        if last_sync_at is None:
            last_sync_at = datetime.utcnow()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (account_id, sync_token, last_sync_at)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    sync_token = excluded.sync_token,
                    last_sync_at = excluded.last_sync_at
                """,
                (account_id, sync_token, last_sync_at)
            )

    def clear_sync_token(self, account_id: str) -> None:
        """
        Clear the sync token for an account (forces full sync).

        Args:
            account_id: The account identifier
        """
        with self.connection() as conn:
            conn.execute(
                "UPDATE sync_state SET sync_token = NULL WHERE account_id = ?",
                (account_id,)
            )

    # =========================================================================
    # Contact Mapping Operations
    # =========================================================================

    def get_contact_mapping(self, matching_key: str) -> Optional[Dict[str, Any]]:
        """
        Get contact mapping by matching key.

        Args:
            matching_key: The normalized contact identifier (name + email)

        Returns:
            Dictionary with mapping details, or None if not found
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    matching_key,
                    account1_resource_name,
                    account2_resource_name,
                    account1_etag,
                    account2_etag,
                    last_synced_hash,
                    created_at,
                    updated_at
                FROM contact_mapping
                WHERE matching_key = ?
                """,
                (matching_key,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def upsert_contact_mapping(
        self,
        matching_key: str,
        account1_resource_name: Optional[str] = None,
        account2_resource_name: Optional[str] = None,
        account1_etag: Optional[str] = None,
        account2_etag: Optional[str] = None,
        last_synced_hash: Optional[str] = None
    ) -> None:
        """
        Insert or update a contact mapping.

        Args:
            matching_key: The normalized contact identifier
            account1_resource_name: Google resource name for account 1
            account2_resource_name: Google resource name for account 2
            account1_etag: ETag for account 1's version
            account2_etag: ETag for account 2's version
            last_synced_hash: Content hash of last synced state
        """
        with self.connection() as conn:
            # Check if mapping exists
            cursor = conn.execute(
                "SELECT id FROM contact_mapping WHERE matching_key = ?",
                (matching_key,)
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing mapping
                updates = []
                params = []

                if account1_resource_name is not None:
                    updates.append("account1_resource_name = ?")
                    params.append(account1_resource_name)
                if account2_resource_name is not None:
                    updates.append("account2_resource_name = ?")
                    params.append(account2_resource_name)
                if account1_etag is not None:
                    updates.append("account1_etag = ?")
                    params.append(account1_etag)
                if account2_etag is not None:
                    updates.append("account2_etag = ?")
                    params.append(account2_etag)
                if last_synced_hash is not None:
                    updates.append("last_synced_hash = ?")
                    params.append(last_synced_hash)

                if updates:
                    updates.append("updated_at = ?")
                    params.append(datetime.utcnow())
                    params.append(matching_key)

                    conn.execute(
                        f"UPDATE contact_mapping SET {', '.join(updates)} WHERE matching_key = ?",
                        params
                    )
            else:
                # Insert new mapping
                conn.execute(
                    """
                    INSERT INTO contact_mapping (
                        matching_key,
                        account1_resource_name,
                        account2_resource_name,
                        account1_etag,
                        account2_etag,
                        last_synced_hash,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        matching_key,
                        account1_resource_name,
                        account2_resource_name,
                        account1_etag,
                        account2_etag,
                        last_synced_hash,
                        datetime.utcnow(),
                        datetime.utcnow()
                    )
                )

    def get_all_contact_mappings(self) -> List[Dict[str, Any]]:
        """
        Get all contact mappings.

        Returns:
            List of all contact mapping dictionaries
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    matching_key,
                    account1_resource_name,
                    account2_resource_name,
                    account1_etag,
                    account2_etag,
                    last_synced_hash,
                    created_at,
                    updated_at
                FROM contact_mapping
                ORDER BY matching_key
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def delete_contact_mapping(self, matching_key: str) -> bool:
        """
        Delete a contact mapping.

        Args:
            matching_key: The normalized contact identifier

        Returns:
            True if a mapping was deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM contact_mapping WHERE matching_key = ?",
                (matching_key,)
            )
            return cursor.rowcount > 0

    def get_mappings_by_resource_name(
        self,
        resource_name: str,
        account: int
    ) -> List[Dict[str, Any]]:
        """
        Get contact mappings by resource name for a specific account.

        Args:
            resource_name: The Google resource name to search for
            account: Account number (1 or 2)

        Returns:
            List of matching contact mapping dictionaries
        """
        column = f"account{account}_resource_name"
        if account not in (1, 2):
            raise ValueError("Account must be 1 or 2")

        with self.connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT
                    matching_key,
                    account1_resource_name,
                    account2_resource_name,
                    account1_etag,
                    account2_etag,
                    last_synced_hash,
                    created_at,
                    updated_at
                FROM contact_mapping
                WHERE {column} = ?
                """,
                (resource_name,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Utility Operations
    # =========================================================================

    def get_mapping_count(self) -> int:
        """
        Get the total number of contact mappings.

        Returns:
            Count of contact mappings
        """
        with self.connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM contact_mapping")
            return cursor.fetchone()[0]

    def clear_all_mappings(self) -> int:
        """
        Delete all contact mappings (use with caution).

        Returns:
            Number of mappings deleted
        """
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM contact_mapping")
            return cursor.rowcount

    def clear_all_state(self) -> None:
        """
        Clear all sync state and contact mappings (full reset).
        """
        with self.connection() as conn:
            conn.execute("DELETE FROM sync_state")
            conn.execute("DELETE FROM contact_mapping")

    def vacuum(self) -> None:
        """
        Vacuum the database to reclaim space and optimize performance.
        """
        with self.connection() as conn:
            conn.execute("VACUUM")
