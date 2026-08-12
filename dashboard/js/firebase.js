// ============================================================
// Kelem Bingo – Client-Side Firestore Emulator
// Replaces the Google Firebase SDK with REST + Socket.IO calls
// to our FastAPI backend (firestore_db / admin_api.py).
// All existing firebase.js consumers remain unchanged.
// ============================================================

(function () {
    // ── Detect API base URL ──────────────────────────────────
    const API_BASE = (function () {
        if (window.BACKEND_URL && window.BACKEND_URL !== 'null' && window.BACKEND_URL !== 'about:blank') return window.BACKEND_URL;
        if (window.API_BASE && window.API_BASE !== 'null' && window.API_BASE !== 'about:blank') return window.API_BASE;
        // Fallback: construct from protocol + host
        try {
            var origin = window.location.origin;
            if (origin && origin !== 'null' && origin !== 'about:blank' && origin !== 'about:srcdoc') return origin;
        } catch(e) {}
        try {
            return window.location.protocol + '//' + window.location.host;
        } catch(e) {}
        return '';
    })();

    // ── Socket.IO Connection ──────────────────────────────────
    var socket = null;
    try {
        if (typeof io === 'undefined') {
            console.warn('[Kelem Bingo] Socket.IO library not loaded (CDN failed). Real-time updates disabled.');
        } else if (API_BASE && API_BASE !== 'null' && API_BASE !== 'about:' && API_BASE !== 'about:blank' && API_BASE !== '') {
            socket = io(API_BASE, {
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionDelay: 1000,
                reconnectionAttempts: Infinity,
            });
        }
    } catch(e) {
        console.warn('[Kelem Bingo] Socket.IO init failed, falling back to polling:', e);
        socket = null;
    }

    if (socket) {
        socket.on('connect', function() {
            console.log('[Kelem Bingo] Socket.IO connected:', socket.id);
        });

        socket.on('disconnect', function() {
            console.log('[Kelem Bingo] Socket.IO disconnected');
        });

        socket.on('reconnect', function() {
            console.log('[Kelem Bingo] Socket.IO reconnected');
        });
    }

    // Track active subscriptions for reconnection
    var _activeSubscriptions = [];

    function _socketSubscription(collection, docId) {
        var sub = { collection: collection };
        if (docId !== undefined && docId !== null) sub.doc_id = docId;
        var playerToken = localStorage.getItem('playerToken');
        var adminToken = localStorage.getItem('token');
        if (playerToken) sub.player_token = playerToken;
        if (adminToken) sub.admin_token = adminToken;
        return sub;
    }

    if (socket) {
        socket.on('connect', function() {
            // Re-subscribe to all active subscriptions on reconnect
            _activeSubscriptions.forEach(function(sub) {
                socket.emit('subscribe', sub);
            });
        });
    }

    // ── Helpers ──────────────────────────────────────────────
    function apiFetch(method, path, body) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        const token = localStorage.getItem('token');
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;
        const playerToken = localStorage.getItem('playerToken');
        if (playerToken) opts.headers['X-Player-Token'] = playerToken;
        if (body !== undefined) opts.body = JSON.stringify(body);
        const url = API_BASE ? (API_BASE + path) : path;
        return fetch(url, opts).then(async r => {
            if (!r.ok) {
                const txt = await r.text();
                throw new Error(`API ${method} ${path} → ${r.status}: ${txt}`);
            }
            return r.json();
        });
    }

    // ── MockTimestamp ─────────────────────────────────────────
    class MockTimestamp {
        constructor(isoString) { this._iso = isoString; }
        toDate() { return new Date(this._iso); }
        toJSON() { return this._iso; }
        static now() { return new MockTimestamp(new Date().toISOString()); }
        static fromDate(d) { return new MockTimestamp(d instanceof Date ? d.toISOString() : d); }
        get serverTimestamp() { return MockTimestamp.now(); }
    }

    // ── MockDocumentSnapshot ─────────────────────────────────
    class MockDocumentSnapshot {
        constructor(id, data, exists, ref) {
            this.id = id;
            this._data = data || {};
            this.exists = exists !== false;
            this.ref = ref;
        }
        data() { return this._data; }
        get(field) { return this._data ? this._data[field] : undefined; }
    }

    // ── MockQuerySnapshot ────────────────────────────────────
    class MockQuerySnapshot {
        constructor(docs) {
            this.docs = docs; // array of MockDocumentSnapshot
            this.size = docs.length;
            this.empty = docs.length === 0;
        }
        forEach(fn) { this.docs.forEach(fn); }
    }

    // ── MockDocumentReference ────────────────────────────────
    class MockDocumentReference {
        constructor(collection, id) {
            this.id = id;
            this._collection = collection;
            this._path = `/api/db/${collection}/${id}`;
        }

        get() {
            return apiFetch('GET', this._path)
                .then(r => new MockDocumentSnapshot(r.id, r.data, true, this))
                .catch(e => {
                    if (e.message.includes('404')) return new MockDocumentSnapshot(this.id, {}, false, this);
                    throw e;
                });
        }

        set(data, opts) {
            const merge = !!(opts && opts.merge);
            return apiFetch('POST', this._path, { data, merge });
        }

        update(data) {
            return apiFetch('PATCH', this._path, { data });
        }

        delete() {
            return apiFetch('DELETE', this._path);
        }

        onSnapshot(onNext, onError) {
            var self = this;
            var sub = _socketSubscription(self._collection, self.id);
            var eventName = 'snapshot';
            var handler = null;

            // Subscribe to Socket.IO room (if available)
            _activeSubscriptions.push(sub);
            if (socket) {
                try { socket.emit('subscribe', sub); } catch(e) {}
            }

            // Listen for updates (if Socket.IO available)
            function _handler(msg) {
                if (msg.collection === self._collection && msg.id === self.id) {
                    var snap = new MockDocumentSnapshot(msg.id, msg.data, msg.exists, self);
                    onNext(snap);
                }
            }
            handler = _handler;
            if (socket) {
                try { socket.on(eventName, handler); } catch(e) {}
            }

            // Send initial snapshot via REST
            this.get().then(onNext).catch(function(e) { if (onError) onError(e); });

            // Return unsubscribe function
            return function() {
                if (socket) {
                    try { socket.off(eventName, handler); } catch(e) {}
                    try { socket.emit('unsubscribe', { collection: self._collection, doc_id: self.id }); } catch(e) {}
                }
                _activeSubscriptions = _activeSubscriptions.filter(function(s) {
                    return !(s.collection === self._collection && s.doc_id === self.id);
                });
            };
        }

        collection(sub) {
            return new MockCollectionReference(`${this._collection}/${this.id}/${sub}`);
        }
    }

    // ── MockQuery ────────────────────────────────────────────
    class MockQuery {
        constructor(collection, filters, orderField, orderDir, limitN) {
            this._collection = collection;
            this._filters = filters || [];
            this._orderField = orderField || null;
            this._orderDir = orderDir || 'ASCENDING';
            this._limitN = limitN || null;
        }

        _buildPath() {
            const params = new URLSearchParams();
            if (this._filters.length) params.set('filters', JSON.stringify(this._filters));
            if (this._orderField) { params.set('order_by', this._orderField); params.set('order_dir', this._orderDir); }
            if (this._limitN !== null) params.set('limit_n', this._limitN);
            const qs = params.toString();
            return `/api/db/${this._collection}${qs ? '?' + qs : ''}`;
        }

        get() {
            return apiFetch('GET', this._buildPath()).then(arr =>
                new MockQuerySnapshot(arr.map(r => new MockDocumentSnapshot(r.id, r.data, true, new MockDocumentReference(this._collection, r.id))))
            );
        }

        where(field, op, value) {
            const newFilters = [...this._filters, [field, op, value]];
            return new MockQuery(this._collection, newFilters, this._orderField, this._orderDir, this._limitN);
        }

        orderBy(field, dir) {
            const d = (dir === 'desc' || dir === firebase.firestore.Query.DESCENDING) ? 'DESCENDING' : 'ASCENDING';
            return new MockQuery(this._collection, this._filters, field, d, this._limitN);
        }

        limit(n) {
            return new MockQuery(this._collection, this._filters, this._orderField, this._orderDir, n);
        }

        onSnapshot(onNext, onError) {
            var self = this;
            var subKey = this._collection + ':' + JSON.stringify(this._filters);
            var handler = null;

            // Subscribe to collection room (if Socket.IO available)
            var subData = _socketSubscription(this._collection);
            if (socket) {
                try { socket.emit('subscribe', subData); } catch(e) {}
            }
            _activeSubscriptions.push(subData);

            function _handler(msg) {
                if (msg.type === 'query_snapshot' && msg.collection === self._collection) {
                    var snap = new MockQuerySnapshot(
                        msg.docs.map(function(d) { return new MockDocumentSnapshot(d.id, d.data, true, new MockDocumentReference(self._collection, d.id)); })
                    );
                    onNext(snap);
                }
            }
            handler = _handler;
            if (socket) {
                try { socket.on('query_snapshot', handler); } catch(e) {}
            }

            // Send initial snapshot via REST
            this.get().then(onNext).catch(function(e) { if (onError) onError(e); });

            return function() {
                if (socket) {
                    try { socket.off('query_snapshot', handler); } catch(e) {}
                    try { socket.emit('unsubscribe', { collection: self._collection }); } catch(e) {}
                }
                _activeSubscriptions = _activeSubscriptions.filter(function(s) {
                    return s.collection !== self._collection;
                });
            };
        }
    }

    // ── MockCollectionReference ──────────────────────────────
    class MockCollectionReference extends MockQuery {
        constructor(name) {
            super(name, [], null, 'ASCENDING', null);
        }

        doc(id) {
            return new MockDocumentReference(this._collection, String(id));
        }

        add(data) {
            return apiFetch('POST', `/api/db/${this._collection}`, { data }).then(r =>
                new MockDocumentReference(this._collection, r.id)
            );
        }
    }

    // ── MockFirestore ────────────────────────────────────────
    class MockFirestore {
        collection(name) { return new MockCollectionReference(name); }
        document(path) {
            const [col, ...rest] = path.split('/');
            return new MockDocumentReference(col, rest.join('/'));
        }
        batch() {
            return {
                _ops: [],
                set(ref, data, opts) { this._ops.push(() => ref.set(data, opts)); return this; },
                update(ref, data) { this._ops.push(() => ref.update(data)); return this; },
                delete(ref) { this._ops.push(() => ref.delete()); return this; },
                commit() { return Promise.all(this._ops.map(op => op())); }
            };
        }
        runTransaction(updateFunction) {
            const txn = {
                get: (ref) => ref.get(),
                update: (ref, data) => ref.update(data),
                set: (ref, data, opts) => ref.set(data, opts)
            };
            return updateFunction(txn);
        }
    }

    // ── MockAuth ─────────────────────────────────────────────
    class MockAuth {
        constructor() {
            this._listeners = [];
            this.currentUser = null;
            this._init();
        }
        _init() {
            let uid = localStorage.getItem('_bingo_anon_uid');
            if (!uid) { uid = 'anon_' + Math.random().toString(36).slice(2); localStorage.setItem('_bingo_anon_uid', uid); }
            this.currentUser = { uid, isAnonymous: true };
            setTimeout(() => this._listeners.forEach(fn => fn(this.currentUser)), 0);
        }
        onAuthStateChanged(fn) { this._listeners.push(fn); if (this.currentUser) setTimeout(() => fn(this.currentUser), 0); }
        signInAnonymously() { return Promise.resolve({ user: this.currentUser }); }
        signOut() { return Promise.resolve(); }
    }

    // ── firebase.firestore.FieldValue helpers ────────────────
    const FieldValue = {
        serverTimestamp: () => ({ __type: 'serverTimestamp', value: new Date().toISOString() }),
        increment: n => ({ __type: 'increment', value: n }),
        arrayUnion: (...items) => ({ __type: 'arrayUnion', values: items }),
        arrayRemove: (...items) => ({ __type: 'arrayRemove', values: items }),
        delete: () => ({ __type: 'delete' }),
    };

    // ── Expose global firebase object ────────────────────────
    const _firestore = new MockFirestore();
    const _auth = new MockAuth();

    window.firebase = {
        apps: [{}],
        initializeApp: () => {},
        firestore: () => _firestore,
        auth: () => _auth,
    };

    // Attach static helpers so existing code like
    //   firebase.firestore.FieldValue.serverTimestamp()
    // and firebase.firestore.Query.DESCENDING still work
    window.firebase.firestore.FieldValue = FieldValue;
    window.firebase.firestore.Timestamp = MockTimestamp;
    window.firebase.firestore.Query = { DESCENDING: 'DESCENDING', ASCENDING: 'ASCENDING' };

    // Also expose db + auth at top level (used by existing scripts)
    window.db = _firestore;
    window.auth = _auth;

    // Expose API_BASE globally (admin scripts reference it directly)
    window.API_BASE = API_BASE;

    // Player-authenticated fetch helper (sends X-Player-Token) for raw fetch calls.
    window.playerApi = function(method, path, body) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        const t = localStorage.getItem('playerToken');
        if (t) opts.headers['X-Player-Token'] = t;
        if (body !== undefined) opts.body = JSON.stringify(body);
        const url = API_BASE ? (API_BASE + path) : path;
        return fetch(url, opts);
    };

    // Expose socket for cartela pool real-time updates
    window._bingoSocket = socket;

    console.log('[Kelem Bingo] Socket.IO bridge loaded. API:', API_BASE, '| Socket:', socket ? 'connected' : 'disabled (REST-only mode)');
})();
