// ==================== AUTH CHECK ====================
(function () {
    var token = localStorage.getItem('token');
    var username = localStorage.getItem('username') || 'Admin';
    var role = localStorage.getItem('role') || 'admin';

    // Fast path: no token -> redirect
    if (!token || !localStorage.getItem('loggedIn')) {
        window.location.href = '/login';
        return;
    }

    function apiBase() {
        return window.BACKEND_URL || window.API_BASE || '';
    }

    // Auto-attach the auth token to every fetch on this (admin) page.
    var origFetch = window.fetch;
    window.fetch = function (url, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        opts.headers['Authorization'] = 'Bearer ' + token;
        return origFetch(url, opts);
    };

    // Server-side verification; hard redirect if the token is invalid/expired.
    fetch(apiBase() + '/api/auth/me', {
        headers: { 'Authorization': 'Bearer ' + token }
    }).then(function (res) {
        if (!res.ok) {
            localStorage.removeItem('token');
            localStorage.removeItem('loggedIn');
            localStorage.removeItem('username');
            localStorage.removeItem('role');
            localStorage.removeItem('displayName');
            window.location.href = '/login';
            return;
        }
        return res.json();
    }).catch(function () {
        // Network error — keep session; pages will surface their own errors.
    });

    var initial = username.charAt(0).toUpperCase();
    var roleLabel = role === 'super_admin' ? 'Super Admin' : 'Admin';
    document.getElementById('sidebarUsername').textContent = username;
    document.getElementById('sidebarRole').textContent = roleLabel;
    document.getElementById('sidebarAvatar').textContent = initial;
    document.getElementById('headerUsername').textContent = username;
    document.getElementById('headerRole').textContent = roleLabel;
    document.getElementById('headerAvatar').textContent = initial;
})();

function logout() {
    var token = localStorage.getItem('token');
    localStorage.removeItem('token');
    localStorage.removeItem('loggedIn');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
    localStorage.removeItem('displayName');
    if (token) {
        try {
            fetch((window.BACKEND_URL || window.API_BASE || '') + '/api/auth/logout', { method: 'POST' });
        } catch (e) {}
    }
    window.location.href = '/login';
}
