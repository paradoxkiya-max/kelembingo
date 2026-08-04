// ==================== ADMIN UTILITIES ====================
function showToast(msg) {
    var el = document.getElementById('toast');
    var textEl = document.getElementById('toast-text');
    if (el && textEl) {
        textEl.textContent = msg;
        el.classList.remove('hidden');
        setTimeout(function() { el.classList.add('hidden'); }, 3000);
    }
}

function animateNum(el, target, dur) {
    if (!el) return;
    var start = 0;
    var startTime = null;
    function step(ts) {
        if (!startTime) startTime = ts;
        var p = Math.min((ts - startTime) / dur, 1);
        var val = Math.round(p * target);
        el.textContent = val.toLocaleString();
        if (p < 1) requestAnimationFrame(step);
    }
    if (target > 0) requestAnimationFrame(step);
    else el.textContent = '0';
}

function fmtTime(ts) {
    if (!ts) return '-';
    try {
        var d;
        if (ts.toDate) { d = ts.toDate(); }
        else if (ts.seconds) { d = new Date(ts.seconds * 1000); }
        else if (typeof ts === 'string' || typeof ts === 'number') { d = new Date(ts); }
        else { return '-'; }
        if (isNaN(d.getTime())) return '-';
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return '-'; }
}

function fmtTimeShort(ts) {
    if (!ts) return '-';
    try {
        var d;
        if (ts.toDate) { d = ts.toDate(); }
        else if (ts.seconds) { d = new Date(ts.seconds * 1000); }
        else if (typeof ts === 'string' || typeof ts === 'number') { d = new Date(ts); }
        else { return '-'; }
        if (isNaN(d.getTime())) return '-';
        var now = new Date();
        var diff = Math.floor((now - d) / 1000);
        if (diff < 60) return diff + 's ago';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        return Math.floor(diff / 86400) + 'd ago';
    } catch (e) { return '-'; }
}

function fmtDate(ts) {
    if (!ts) return '';
    try {
        var d;
        if (ts.toDate) { d = ts.toDate(); }
        else if (ts.seconds) { d = new Date(ts.seconds * 1000); }
        else if (typeof ts === 'string' || typeof ts === 'number') { d = new Date(ts); }
        else { return ''; }
        if (isNaN(d.getTime())) return '';
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (e) { return ''; }
}

function fmtDateFull(ts) {
    if (!ts) return 'Unknown';
    try {
        var d;
        if (ts.toDate) { d = ts.toDate(); }
        else if (ts.seconds) { d = new Date(ts.seconds * 1000); }
        else if (typeof ts === 'string' || typeof ts === 'number') { d = new Date(ts); }
        else { return 'Unknown'; }
        if (isNaN(d.getTime())) return 'Unknown';
        return d.toLocaleString();
    } catch (e) { return 'Unknown'; }
}

function hashStr(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0; }
    return h;
}

function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function api(method, path, body) {
    var opts = {
        method: method,
        headers: { 'Content-Type': 'application/json' }
    };
    var token = localStorage.getItem('token');
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(API_BASE + path, opts).then(function (res) {
        if (!res.ok) {
            return res.text().then(function (txt) {
                throw new Error(txt || 'API Error');
            });
        }
        return res.json();
    });
}

