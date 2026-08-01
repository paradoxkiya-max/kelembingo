// ==================== STATE ====================
var currentUser = null;
var currentScreen = 'home';
var currentRoundId = null;
var currentStake = 10;
var roundUnsubscribe = null;
var userUnsubscribe = null;
var statsUnsubscribe = null;
var statsInterval = null;
var selectedCartelas = [];
var myCartelas = {};
var autoMarkEnabled = false;
var calledNumbers = new Set();
var gameCountdownInterval = null;
var selectionCountdownInterval = null;
var winCountdownInterval = null;
var listenerReady = false;
var isSpectator = false;
var _lastKnownPlayerCount = 0;
var serverTimeOffset = 0;

var SELECTION_DURATION = 45; // seconds for card selection phase

function serverNow() {
    return Date.now() + serverTimeOffset;
}

var _timeSyncInterval = null;
async function syncServerTime() {
    try {
        var before = Date.now();
        var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        var res = await fetch(apiBase + '/api/time');
        var after = Date.now();
        var data = await res.json();
        var serverMs = new Date(data.iso).getTime();
        var rtt = after - before;
        var clientMid = before + Math.floor(rtt / 2);
        serverTimeOffset = serverMs - clientMid;
        console.log('[TimeSync] offset=' + serverTimeOffset + 'ms, rtt=' + rtt + 'ms');
    } catch (e) {
        console.warn('[TimeSync] Failed, using local clock:', e);
        serverTimeOffset = 0;
    }
}

function startTimeSync() {
    syncServerTime();
    if (_timeSyncInterval) clearInterval(_timeSyncInterval);
    _timeSyncInterval = setInterval(syncServerTime, 30000);
}

// Audio state
var musicEnabled = false;
var voiceEnabled = true;
var masterVolume = 0.8;
var bgMusicAudio = null;
var audioCtx = null;

// Telegram WebApp
var tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#0D1117');
    tg.setBackgroundColor('#0D1117');
}
