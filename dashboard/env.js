(function () {
    var host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
        window.BACKEND_URL = window.location.origin;
    } else {
        window.BACKEND_URL = 'https://kelembingo-gateway-gjfl.onrender.com';
    }
    window.API_BASE = window.BACKEND_URL;
})();
