import os
import sys
import json
import uuid
from datetime import datetime, date, timezone
import logging
import sqlalchemy
from sqlalchemy import create_engine, Column, String, Text, DateTime, func
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
        return self._data if self.exists else None
        
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

    def update(self, ref, data):
        ref._session = self._session
        ref.update(data)

    def set(self, ref, data, merge=False):
        ref._session = self._session
        ref.set(data, merge=merge)

    def delete(self, ref):
        ref._session = self._session
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
        # Convert dotted field to json_extract path: 'ocr.status' -> '$.ocr.status'
        json_path = '$.' + field
        extract = func.json_extract(FirestoreDocument.data, json_path)

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
            # json_each for array containment — fall back to Python filter
            return None, {}

        maker = op_map.get(op)
        if maker is None:
            return None, {}

        # Handle type coercion — extract returns text, cast for numeric comparisons
        # SQLite's json_extract returns typed values for numbers/booleans
        clause = maker(extract, val)
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
                json_path = '$.' + field
                extract = func.json_extract(FirestoreDocument.data, json_path)
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
                # Normalize any corrupt __type artifacts in the stored value
                curr_val = target.get(last_part)
                if isinstance(curr_val, dict) and '__type' in curr_val:
                    curr_val = curr_val.get('value', 0)
                else:
                    curr_val = curr_val or 0
                # Convert serialized FieldValue objects from frontend JSON
                if isinstance(v, dict) and v.get('__type') == 'increment':
                    inc = Increment(v.get('value', 0))
                    target[last_part] = curr_val + inc.value
                elif isinstance(v, Increment):
                    target[last_part] = curr_val + v.value
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
                elif isinstance(v, dict) and v.get('__type') == 'serverTimestamp':
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
    """Recursively fix any {__type: ..., value: ...} artifacts stored by old FieldValue mocks."""
    if isinstance(data, dict):
        if '__type' in data and 'value' in data:
            return data['value']
        return {k: normalize_doc(v) for k, v in data.items()}
    if isinstance(data, list):
        return [normalize_doc(v) for v in data]
    return data


def fix_playwallet():
    """
    Fix all user documents that have {__type: increment, value: N} stored
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
                if isinstance(val, dict) and '__type' in val:
                    data[key] = val.get('value', 0)
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
    sess = SessionLocal()
    try:
        for collection, docs in dump.items():
            if not isinstance(docs, dict):
                continue
            for doc_id, data in docs.items():
                clean = normalize_doc(data) if isinstance(data, dict) else data
                existing = sess.query(FirestoreDocument).filter(
                    FirestoreDocument.collection == collection,
                    FirestoreDocument.doc_id == str(doc_id),
                ).first()
                payload = json.dumps(clean if isinstance(clean, dict) else {})
                if existing:
                    if overwrite:
                        existing.data = payload
                        stats['overwritten'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    sess.add(FirestoreDocument(
                        collection=collection,
                        doc_id=str(doc_id),
                        data=payload,
                    ))
                    stats['inserted'] += 1
        sess.commit()
        return stats
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
