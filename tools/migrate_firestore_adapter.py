#!/usr/bin/env python3
"""Copy KelemBingo's Firestore-style SQL adapter tables to PostgreSQL.

The utility is intentionally separate from the runtime. It reads SOURCE_DATABASE_URL
and TARGET_DATABASE_URL from the environment, supports --dry-run, and never deletes
source rows. Run it first against a verified manual backup or a read-only source copy.
"""

import argparse
import os
from contextlib import closing

from sqlalchemy import create_engine, text


TABLES = {
    "firestore_documents": (
        "collection",
        "doc_id",
        "data",
        "created_at",
        "updated_at",
    ),
    "system_events": (
        "id",
        "collection",
        "doc_id",
        "event_type",
        "created_at",
    ),
    "operation_records": (
        "operation_key",
        "operation",
        "result",
        "created_at",
    ),
    "account_locks": (
        "user_id",
        "created_at",
    ),
}


def normalize_url(value: str) -> str:
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql://", 1)
    return value


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def count_rows(conn, table: str) -> int:
    return int(conn.execute(text(f"select count(*) from {quote_identifier(table)}")).scalar_one())


def upsert_sql(table: str, columns: tuple[str, ...], dialect: str) -> str:
    quoted_table = quote_identifier(table)
    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    if table == "firestore_documents":
        conflict = "(\"collection\", \"doc_id\")"
        updates = ", ".join(
            f'{quote_identifier(column)} = excluded.{quote_identifier(column)}'
            for column in columns
            if column not in {"collection", "doc_id", "created_at"}
        )
    elif table == "system_events":
        conflict = "(\"id\")"
        updates = ", ".join(
            f'{quote_identifier(column)} = excluded.{quote_identifier(column)}'
            for column in columns
            if column != "id"
        )
    elif table == "operation_records":
        conflict = "(\"operation_key\")"
        updates = ", ".join(
            f'{quote_identifier(column)} = excluded.{quote_identifier(column)}'
            for column in columns
            if column not in {"operation_key", "created_at"}
        )
    else:
        conflict = "(\"user_id\")"
        updates = ""
    if dialect == "postgresql":
        if updates:
            return f"insert into {quoted_table} ({quoted_columns}) values ({placeholders}) on conflict {conflict} do update set {updates}"
        return f"insert into {quoted_table} ({quoted_columns}) values ({placeholders}) on conflict {conflict} do nothing"
    # SQLite is supported for local dry-run/copy testing.
    if updates:
        set_clause = ", ".join(
            f'{quote_identifier(column)} = excluded.{quote_identifier(column)}'
            for column in columns
            if column not in {"collection", "doc_id", "operation_key", "id", "user_id", "created_at"}
        )
        return f"insert into {quoted_table} ({quoted_columns}) values ({placeholders}) on conflict do update set {set_clause}"
    return f"insert or ignore into {quoted_table} ({quoted_columns}) values ({placeholders})"


def migrate(source_url: str, target_url: str, batch_size: int, dry_run: bool) -> None:
    source = create_engine(normalize_url(source_url), pool_pre_ping=True)
    target = create_engine(normalize_url(target_url), pool_pre_ping=True)
    try:
        with source.connect() as source_conn, target.connect() as target_conn:
            source_tables = set(source.dialect.get_table_names(source_conn))
            target_tables = set(target.dialect.get_table_names(target_conn))
            missing_source = set(TABLES) - source_tables
            missing_target = set(TABLES) - target_tables
            if missing_source:
                raise RuntimeError(f"Source is missing adapter tables: {sorted(missing_source)}")
            if missing_target:
                raise RuntimeError(f"Target is missing adapter tables: {sorted(missing_target)}")

            print("SOURCE_COUNTS")
            source_counts = {}
            for table in TABLES:
                source_counts[table] = count_rows(source_conn, table)
                print(f"{table}: {source_counts[table]}")
            if dry_run:
                print("DRY_RUN: no target writes performed")
                return

            # SQLAlchemy 2.x may leave an implicit read transaction open after
            # schema introspection/counts. Close that read-only transaction before
            # opening the single atomic target write transaction.
            target_conn.commit()
            target_tx = target_conn.begin()
            try:
                for table, columns in TABLES.items():
                    print(f"COPYING {table}")
                    query = text(
                        f"select {', '.join(quote_identifier(column) for column in columns)} "
                        f"from {quote_identifier(table)}"
                    )
                    upsert = text(upsert_sql(table, columns, target.dialect.name))
                    result = source_conn.execution_options(stream_results=True).execute(query)
                    copied = 0
                    while True:
                        rows = result.fetchmany(batch_size)
                        if not rows:
                            break
                        target_conn.execute(upsert, [dict(row._mapping) for row in rows])
                        copied += len(rows)
                    print(f"COPIED {table}: {copied}")
                target_tx.commit()
            except Exception:
                target_tx.rollback()
                raise

            print("TARGET_COUNTS")
            for table in TABLES:
                print(f"{table}: {count_rows(target_conn, table)}")
    finally:
        source.dispose()
        target.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count source rows and validate both schemas without writing")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per target batch")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not source_url or not target_url:
        parser.error("SOURCE_DATABASE_URL and TARGET_DATABASE_URL must be set in the environment")
    migrate(source_url, target_url, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
