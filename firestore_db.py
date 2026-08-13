import os
import sys
import json
import uuid
from datetime import datetime, date, timezone
import logging
import sqlalchemy
from sqlalchemy import create_engine, Column, String, Text, DateTime, Numeric, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Determine DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///kelembingo.db"
elif DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy 1.4+ requires postgresql:// instead of postgres://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_timeout=30,
)
if "sqlite" in DATABASE_URL:
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("PRAGMA journal_mode=WAL"))
        conn.execute(sqlalchemy.text("PRAGMA busy_timeout=30000"))
        conn.execute(sqlalchemy.text("PRAGMA synchronous=NORMAL"))
        conn.execute(sqlalchemy.text("PRAGMA temp_store=MEMORY"))
        conn.execute(sqlalchemy.text("PRAGMA cache_size=-64000"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FirestoreDocument(Base):
    __tablename__ = 'firestore_documents'
    collection = Column(String, primary_key=True)
    doc_id = Column(String, primary_key=True)
    data = Column(Text)  # JSON string representation
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SystemEvent(Base):
    __tablename__ = 'system_events'
    id = Column(String, primary_key=True)
    collection = Column(String)
    doc_id = Column(String)
    event_type = Column(String)  # 'set', 'update', 'delete'
    created_at = Column(DateTime, default=datetime.utcnow)


class OperationRecord(Base):
    """Durable idempotency record for money and game state transitions."""
    __tablename__ = 'operation_records'
    operation_key = Column(String, primary_key=True)
    operation = Column(String, nullable=False)
    result = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AccountLock(Base):
    """Stable rows that can be locked while mutating one user's wallet."""
    __tablename__ = 'account_locks'
    user_id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables (defensively catch race conditions under concurrent multi-process startup)
try:
    Base.metadata.create_all(bind=engine, checkfirst=True)
except Exception as e:
    logger.warning(f"Could not run create_all (might already be created/locked): {e}")

# Firestore Field Special Values
class Increment:
    def __init__(self, value):
        self.value = value

class ArrayUnion:
    def __init__(self, values):
        self.values = values if isinstance(values, list) else [values]

class ArrayRemove:
    def __init__(self, values):
        self.values = values if isinstance(values, list) else [values]

class FieldFilter:
    def __init__(self, field, op, value):
        self.field = field
        self.op = op
        self.value = value

# Emulator Classes
class DocumentSnapshot:
    def __init__(self, doc_id, data, exists=True):
        self.id = str(doc_id)
        self._data = data
        self.exists = exists

    def to_dict(self):
        if not self.exists or self._data is None:
            return None
        return normalize_doc(self._data)
        
    def data(self):
        return self._data
        
    def get(self, field_path):
        return self._data.get(field_path)

class _FirestoreQuery:
    DESCENDING = "DESCENDING"
    ASCENDING = "ASCENDING"

class MockFirestoreClient:
    Query = _FirestoreQuery

    def collection(self, name):
        return CollectionRef(name)

    def document(self, path):
        # Support full paths like "collection/doc_id"
        parts = path.split('/', 1)
        if len(parts) == 2:
            return DocumentRef(parts[0], parts[1])
        raise ValueError("Invalid document path")

    def transaction(self):
        return Transaction(SessionLocal())

    def batch(self, skip_events=False):
        return WriteBatch(skip_events=skip_events)

class Transaction:
    def __init__(self, session):
        self._session = session

    def get(self, ref):
        ref._session = self._session
        return ref.get()

    def query(self, ref):
        ref._session = self._session
        return ref

    def update(self, ref, data):
        ref._session = self._session
        ref._in_batch = True
        ref.update(data)

    def set(self, ref, data, merge=False):
        ref._session = self._session
        ref._in_batch = True
        ref.set(data, merge=merge)

    def delete(self, ref):
        ref._session = self._session
        ref._in_batch = True
        ref.delete()

def transactional(func):
    def wrapper(transaction, *args, **kwargs):
        sess = transaction._session
        try:
            result = func(transaction, *args, **kwargs)
            sess.commit()
            return result
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()
    return wrapper

def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _ensure_account_lock(session, key: str):
    """Create a lock row without failing if another process created it first."""
    key = str(key)
    if engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        session.add(AccountLock(user_id=key))
        session.flush()
        return
    statement = insert(AccountLock).values(user_id=key).on_conflict_do_nothing(
        index_elements=[AccountLock.user_id]
    )
    session.execute(statement)


def run_idempotent(operation_key: str, operation: str, callback, lock_key=None, lock_keys=None):
    """Run a transaction once across processes and return the stored result on retry.

    The callback receives a repository Transaction. Its document writes and the
    unique operation record commit together. If another process wins the same
    operation key, the losing transaction rolls back and returns the winner's
    stored result without repeating the side effect.
    """
    sess = SessionLocal()
    try:
        requested_locks = list(lock_keys or [])
        if lock_key is not None:
            requested_locks.append(lock_key)
        for key in sorted({str(value) for value in requested_locks}):
            _ensure_account_lock(sess, key)
            sess.query(AccountLock).filter(AccountLock.user_id == key).with_for_update().one()

        existing = sess.query(OperationRecord).filter(
            OperationRecord.operation_key == str(operation_key)
        ).first()
        if existing:
            return json.loads(existing.result)

        transaction = Transaction(sess)
        result = callback(transaction)
        record = OperationRecord(
            operation_key=str(operation_key),
            operation=str(operation),
            result=json.dumps(result, default=_json_default),
        )
        sess.add(record)
        sess.commit()
        return result
    except IntegrityError:
        sess.rollback()
        # A concurrent transaction may have inserted the same operation key.
        winner = sess.query(OperationRecord).filter(
            OperationRecord.operation_key == str(operation_key)
        ).first()
        if winner:
            return json.loads(winner.result)
        raise
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


class WriteBatch:
    def __init__(self, skip_events=False):
        self._session = SessionLocal()
        self._operations = []
        self._skip_events = skip_events

    def set(self, ref, data, merge=False):
        ref._session = self._session
        ref._in_batch = True
        ref._skip_events = self._skip_events
        self._operations.append(lambda: ref.set(data, merge=merge))

    def update(self, ref, data):
        ref._session = self._session
        ref._in_batch = True
        ref._skip_events = self._skip_events
        self._operations.append(lambda: ref.update(data))

    def delete(self, ref):
        ref._session = self._session
        ref._in_batch = True
        ref._skip_events = self._skip_events
        self._operations.append(lambda: ref.delete())

    def commit(self):
        import time as _time
        logger.debug(f"[CART-DBG] WriteBatch.commit() START - {len(self._operations)} ops, skip_events={self._skip_events}")
        t0 = _time.monotonic()
        try:
            for i, op in enumerate(self._operations):
                op()
            logger.debug(f"[CART-DBG] All {len(self._operations)} ops executed in {round(_time.monotonic()-t0, 3)}s, committing session...")
            self._session.commit()
            logger.debug(f"[CART-DBG] WriteBatch.commit() DONE in {round(_time.monotonic()-t0, 3)}s")
        except Exception as e:
            logger.error(f"[CART-DBG] WriteBatch.commit() FAILED: {e}")
            self._session.rollback()
            raise
        finally:
            self._session.close()

_NUMERIC_QUERY_FIELDS = {
    "number", "stake", "wins", "prize", "amount", "balance", "bonus",
    "wallet", "play_wallet", "cartela_number",
}


def _json_scalar_expr(field: str):
    """Return a dialect-compatible scalar expression for a JSON document field."""
    path = field.split(".")
    if engine.dialect.name == "postgresql":
        return func.jsonb_extract_path_text(
            cast(FirestoreDocument.data, JSONB), *path
        )
    return func.json_extract(FirestoreDocument.data, "$." + field)


def _sql_scalar_value(value):
    """Normalize Firestore values for PostgreSQL text scalar extraction."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class CollectionRef:
    def __init__(self, collection_name, session=None):
        self.collection_name = collection_name
        self._session = session
        self._filters = []
        self._order_by = None
        self._limit = None

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return DocumentRef(self.collection_name, str(doc_id), self._session)

    def where(self, field=None, op=None, value=None, filter=None):
        if filter is not None:
            field = filter.field
            op = getattr(filter, 'op', getattr(filter, 'operator', '=='))
            value = filter.value
        q = CollectionRef(self.collection_name, self._session)
        q._filters = list(self._filters) + [(field, op, value)]
        q._order_by = self._order_by
        q._limit = self._limit
        return q

    def order_by(self, field, direction="ASCENDING"):
        q = CollectionRef(self.collection_name, self._session)
        q._filters = list(self._filters)
        q._order_by = (field, direction)
        q._limit = self._limit
        return q

    def limit(self, n):
        q = CollectionRef(self.collection_name, self._session)
        q._filters = list(self._filters)
        q._order_by = self._order_by
        q._limit = n
        return q

    def _build_sql_filter(self, field: str, op: str, val) -> tuple:
        """Build a SQLAlchemy WHERE clause from a Firestore-style filter.
        Returns (clause, params_dict) or (None, {}) if not convertible."""
        extract = _json_scalar_expr(field)
        field_name = field.rsplit('.', 1)[-1]
        is_postgres = engine.dialect.name == "postgresql"
        if is_postgres and field_name in _NUMERIC_QUERY_FIELDS:
            extract = cast(extract, Numeric)

        op_map = {
            '==': lambda col, v: col == v,
            'equal': lambda col, v: col == v,
            'equals': lambda col, v: col == v,
            '!=': lambda col, v: col != v,
            'not-equal': lambda col, v: col != v,
            '>': lambda col, v: col > v,
            'greater-than': lambda col, v: col > v,
            '>=': lambda col, v: col >= v,
            'greater-than-or-equal': lambda col, v: col >= v,
            '<': lambda col, v: col < v,
            'less-than': lambda col, v: col < v,
            '<=': lambda col, v: col <= v,
            'less-than-or-equal': lambda col, v: col <= v,
            'in': lambda col, v: col.in_(v),
            'array-contains': None,  # needs special handling
        }

        if op == 'array-contains':
            # Fall back to Python-side filtering for array containment.
            return None, {}

        maker = op_map.get(op)
        if maker is None:
            return None, {}

        if op == 'in':
            sql_val = [
                value if not is_postgres
                else (
                    value if field_name in _NUMERIC_QUERY_FIELDS
                    else _sql_scalar_value(value)
                )
                for value in val
            ]
        elif not is_postgres:
            sql_val = val
        elif field_name in _NUMERIC_QUERY_FIELDS:
            sql_val = val
        else:
            sql_val = _sql_scalar_value(val)

        clause = maker(extract, sql_val)
        return clause, {}

    def _execute_query(self):
        sess = self._session or SessionLocal()
        try:
            query = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection == self.collection_name
            )

            # Apply SQL-level filters where possible
            python_filters = []
            for field, op, val in self._filters:
                clause, _ = self._build_sql_filter(field, op, val)
                if clause is not None:
                    query = query.filter(clause)
                else:
                    # Fall back to Python-side filter
                    python_filters.append((field, op, val))

            # Apply ordering at SQL level if possible
            if self._order_by:
                field, direction = self._order_by
                extract = _json_scalar_expr(field)
                if engine.dialect.name == "postgresql" and field.rsplit('.', 1)[-1] in _NUMERIC_QUERY_FIELDS:
                    extract = cast(extract, Numeric)
                if "DESC" in str(direction).upper():
                    query = query.order_by(extract.desc())
                else:
                    query = query.order_by(extract.asc())

            # Apply limit at SQL level
            if self._limit is not None:
                query = query.limit(self._limit)

            db_docs = query.all()

            docs = []
            for db_doc in db_docs:
                try:
                    data = json.loads(db_doc.data)
                except Exception:
                    data = {}
                docs.append(DocumentSnapshot(db_doc.doc_id, data, exists=True))

            # Apply any remaining Python-side filters (array-contains etc.)
            if python_filters:
                filtered_docs = []
                for doc in docs:
                    match = True
                    doc_data = doc.to_dict()
                    for field, op, val in python_filters:
                        doc_val = doc_data
                        for part in field.split('.'):
                            if isinstance(doc_val, dict):
                                doc_val = doc_val.get(part)
                            else:
                                doc_val = None
                                break
                        if op == 'array-contains':
                            if not isinstance(doc_val, list) or val not in doc_val:
                                match = False
                        else:
                            # Re-check with Python comparison
                            if op in ['==', 'equal', 'equals']:
                                if doc_val != val: match = False
                            elif op in ['!=', 'not-equal']:
                                if doc_val == val: match = False
                    if match:
                        filtered_docs.append(doc)
                docs = filtered_docs

            return docs
        finally:
            if not self._session:
                sess.close()

    def get(self):
        return self._execute_query()

    def stream(self):
        return iter(self._execute_query())

    def add(self, data):
        doc_id = str(uuid.uuid4())
        ref = DocumentRef(self.collection_name, doc_id, self._session)
        ref.set(data)
        return ref

class DocumentRef:
    def __init__(self, collection_name, doc_id, session=None):
        self.collection_name = collection_name
        self.id = str(doc_id)
        self._session = session
        self._in_batch = False
        self._skip_events = False

    def get(self, transaction=None):
        sess = self._session or SessionLocal()
        try:
            db_doc = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection == self.collection_name,
                FirestoreDocument.doc_id == self.id
            ).first()
            if db_doc:
                try:
                    data = json.loads(db_doc.data)
                except Exception:
                    data = {}
                return DocumentSnapshot(self.id, data, exists=True)
            else:
                return DocumentSnapshot(self.id, {}, exists=False)
        finally:
            if not self._session:
                sess.close()

    def set(self, data, merge=False):
        sess = self._session or SessionLocal()
        try:
            db_doc = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection == self.collection_name,
                FirestoreDocument.doc_id == self.id
            ).first()
            
            clean_data = self._clean_data_dict(data)

            if db_doc:
                if merge:
                    curr = json.loads(db_doc.data) if db_doc.data else {}
                    curr.update(clean_data)
                    db_doc.data = json.dumps(curr)
                else:
                    db_doc.data = json.dumps(clean_data)
            else:
                db_doc = FirestoreDocument(
                    collection=self.collection_name,
                    doc_id=self.id,
                    data=json.dumps(clean_data)
                )
                sess.add(db_doc)
            
            if not self._skip_events:
                event = SystemEvent(
                    id=str(uuid.uuid4()),
                    collection=self.collection_name,
                    doc_id=self.id,
                    event_type='set'
                )
                sess.add(event)
            if not self._in_batch:
                sess.commit()
            else:
                self._in_batch = False
                self._skip_events = False
        except Exception:
            sess.rollback()
            raise
        finally:
            if not self._session:
                sess.close()

    def update(self, data):
        sess = self._session or SessionLocal()
        try:
            db_doc = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection == self.collection_name,
                FirestoreDocument.doc_id == self.id
            ).first()
            if not db_doc:
                raise ValueError(f"Document {self.collection_name}/{self.id} does not exist.")
            
            curr = json.loads(db_doc.data) if db_doc.data else {}
            
            for k, v in data.items():
                parts = k.split('.')
                target = curr
                for part in parts[:-1]:
                    if part not in target or not isinstance(target[part], dict):
                        target[part] = {}
                    target = target[part]

                last_part = parts[-1]
                # Normalize any corrupt __type / _type artifacts in the stored value
                curr_val = target.get(last_part)
                if isinstance(curr_val, dict) and ('__type' in curr_val or '_type' in curr_val):
                    curr_val = curr_val.get('value', 0)
                elif not isinstance(curr_val, (int, float)):
                    curr_val = 0
                # Convert serialized FieldValue objects from REST/JSON
                if isinstance(v, dict) and (v.get('__type') in ('increment', 'Increment') or v.get('_type') in ('increment', 'Increment')):
                    inc_val = float(v.get('value', 0))
                    target[last_part] = float(curr_val) + inc_val
                elif isinstance(v, Increment):
                    target[last_part] = float(curr_val) + float(v.value)
                elif isinstance(v, ArrayUnion):
                    lst = target.get(last_part, [])
                    if not isinstance(lst, list):
                        lst = []
                    for item in v.values:
                        if item not in lst:
                            lst.append(item)
                    target[last_part] = lst
                elif isinstance(v, ArrayRemove):
                    lst = target.get(last_part, [])
                    if not isinstance(lst, list):
                        lst = []
                    target[last_part] = [x for x in lst if x not in v.values]
                elif isinstance(v, dict) and (v.get('__type') == 'serverTimestamp' or v.get('_type') == 'serverTimestamp'):
                    target[last_part] = datetime.now(tz=timezone.utc).isoformat()
                else:
                    target[last_part] = self._serialize_val(v)
            
            db_doc.data = json.dumps(curr)
            
            if not self._skip_events:
                event = SystemEvent(
                    id=str(uuid.uuid4()),
                    collection=self.collection_name,
                    doc_id=self.id,
                    event_type='update'
                )
                sess.add(event)
            if not self._in_batch:
                sess.commit()
            else:
                self._in_batch = False
                self._skip_events = False
        except Exception:
            sess.rollback()
            raise
        finally:
            if not self._session:
                sess.close()

    def delete(self):
        sess = self._session or SessionLocal()
        try:
            db_doc = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection == self.collection_name,
                FirestoreDocument.doc_id == self.id
            ).first()
            if db_doc:
                sess.delete(db_doc)
            
            if not self._skip_events:
                event = SystemEvent(
                    id=str(uuid.uuid4()),
                    collection=self.collection_name,
                    doc_id=self.id,
                    event_type='delete'
                )
                sess.add(event)
            if not self._in_batch:
                sess.commit()
            else:
                self._in_batch = False
                self._skip_events = False
        except Exception:
            sess.rollback()
            raise
        finally:
            if not self._session:
                sess.close()

    def _clean_data_dict(self, data):
        cleaned = {}
        for k, v in data.items():
            if isinstance(v, dict) and v.get('__type') == 'serverTimestamp':
                cleaned[k] = datetime.now(tz=timezone.utc).isoformat()
            elif isinstance(v, dict) and v.get('__type') == 'increment':
                cleaned[k] = v.get('value', 0)
            else:
                cleaned[k] = self._serialize_val(v)
        return cleaned

    def _serialize_val(self, val):
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if hasattr(val, 'to_datetime'):
            return val.to_datetime().isoformat()
        if isinstance(val, dict):
            return {k: self._serialize_val(v) for k, v in val.items()}
        if isinstance(val, list):
            return [self._serialize_val(v) for v in val]
        return val


# ═══════════════════════════════════════════════════════════════════
# Whole-database export / import (used by the JSON backup workflow)
# ═══════════════════════════════════════════════════════════════════
def normalize_doc(data: dict) -> dict:
    """Recursively fix any {__type: ..., value: ...} or {_type: ..., value: ...} artifacts stored by old FieldValue mocks or REST payload."""
    if isinstance(data, dict):
        if ('__type' in data or '_type' in data) and 'value' in data:
            val = data['value']
            return float(val) if isinstance(val, (int, float)) else val
        return {k: normalize_doc(v) for k, v in data.items()}
    if isinstance(data, list):
        return [normalize_doc(v) for v in data]
    return data


def fix_playwallet():
    """
    Fix all user documents that have {__type: increment, value: N} or {_type: Increment, value: N} stored
    instead of a plain number for play_wallet / balance / bonus fields.
    Safe to run multiple times — idempotent after the first run.
    """
    sess = SessionLocal()
    try:
        docs = sess.query(FirestoreDocument).filter(
            FirestoreDocument.collection == 'users'
        ).all()
        fixed = 0
        for doc in docs:
            data = json.loads(doc.data) if doc.data else {}
            changed = False
            for key in ('play_wallet', 'balance', 'bonus'):
                val = data.get(key)
                if isinstance(val, dict) and ('__type' in val or '_type' in val):
                    data[key] = float(val.get('value', 0))
                    changed = True
            if changed:
                doc.data = json.dumps(data)
                fixed += 1
        sess.commit()
        return fixed
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def export_all() -> dict:
    """
    Dump every stored document to a plain dict:
        { collection_name: { doc_id: {..data..}, ... }, ... }

    The `system_events` audit trail is intentionally excluded — only the
    document store is backed up.
    """
    sess = SessionLocal()
    try:
        out: dict = {}
        for row in sess.query(FirestoreDocument).all():
            try:
                data = json.loads(row.data) if row.data else {}
            except Exception:
                data = {}
            out.setdefault(row.collection, {})[row.doc_id] = normalize_doc(data)
        return out
    finally:
        sess.close()


def count_documents() -> int:
    """Total number of stored documents (used to detect an empty DB)."""
    sess = SessionLocal()
    try:
        return sess.query(FirestoreDocument).count()
    finally:
        sess.close()


def delete_all_documents() -> dict:
    """Delete every document and system event from the store. Returns rows deleted per table."""
    sess = SessionLocal()
    try:
        docs = sess.query(FirestoreDocument).delete()
        events = sess.query(SystemEvent).delete()
        sess.commit()
        return {"documents": docs, "events": events}
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def import_all(dump: dict, overwrite: bool = False) -> dict:
    """
    Seed documents from an export_all()-shaped dict.

    overwrite=False (default): only insert documents that don't already exist
    (safe restore — never clobbers newer live data).
    overwrite=True: replace existing documents with the backup's version.

    Returns {'inserted': n, 'skipped': n, 'overwritten': n}.
    """
    stats = {'inserted': 0, 'skipped': 0, 'overwritten': 0}
    if not isinstance(dump, dict):
        return stats

    # Prefetch the existing rows once. The previous implementation issued a
    # SELECT for every document, which made a fresh PostgreSQL restore of the
    # Telegram snapshot (8,355 documents) slow enough to prevent Render from
    # detecting the web port while startup was still in progress.
    collections = [
        collection for collection, docs in dump.items()
        if isinstance(docs, dict)
    ]
    sess = SessionLocal()
    try:
        existing_by_key = {}
        if collections:
            existing_rows = sess.query(FirestoreDocument).filter(
                FirestoreDocument.collection.in_(collections)
            ).all()
            existing_by_key = {
                (row.collection, row.doc_id): row for row in existing_rows
            }

        processed = 0
        for collection in collections:
            docs = dump[collection]
            for doc_id, data in docs.items():
                doc_key = (collection, str(doc_id))
                clean = normalize_doc(data) if isinstance(data, dict) else data
                payload = json.dumps(clean if isinstance(clean, dict) else {})
                existing = existing_by_key.get(doc_key)
                if existing:
                    if overwrite:
                        existing.data = payload
                        stats['overwritten'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    row = FirestoreDocument(
                        collection=collection,
                        doc_id=str(doc_id),
                        data=payload,
                    )
                    sess.add(row)
                    existing_by_key[doc_key] = row
                    stats['inserted'] += 1

                processed += 1
                if processed % 1000 == 0:
                    logger.info(
                        "Restore prepared %s documents (inserted=%s skipped=%s overwritten=%s)",
                        processed, stats['inserted'], stats['skipped'], stats['overwritten'],
                    )

        sess.commit()
        return stats
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
