// ==================== AUTH / USER ====================
function getTelegramUser() {
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id) return tg.initDataUnsafe.user;
    if (tg && tg.initData && tg.initData.length > 10) {
        try { var p = new URLSearchParams(tg.initData); var u = p.get('user'); if (u) return JSON.parse(u); } catch(e) {}
    }
    return null;
}

function getTelegramInitData() {
    if (tg && tg.initData && tg.initData.length > 10) return tg.initData;
    return '';
}

async function bootstrapPlayerToken() {
    var initData = getTelegramInitData();
    if (!initData) return null;
    var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
    var res = await fetch(apiBase + '/api/player/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initData: initData })
    });
    if (!res.ok) throw new Error((await res.json().catch(function() { return {}; })).detail || 'Player auth failed');
    var data = await res.json();
    if (data.token) localStorage.setItem('playerToken', data.token);
    return data;
}

async function initUser() {
    await startTimeSync();

    if (!tg) {
        var ug = document.getElementById('user-greeting');
        if (ug) ug.textContent = '';
        var hero = document.querySelector('#screen-home .glass.rounded-2xl.p-5');
        if (hero) hero.innerHTML = '<div class="text-3xl mb-2">📱</div><h2 class="text-lg font-bold text-white mb-2">Open from Telegram</h2><p class="text-sm text-white/60 mb-4">Please open this game from the Telegram bot.</p><a href="https://t.me/kelembingobot" target="_blank" class="inline-block gradient-orange text-white px-6 py-3 rounded-xl font-semibold text-sm">Open Bot</a>';
        return;
    }

    var tgUser = getTelegramUser();
    if (!tgUser || !tgUser.id) {
        for (var i = 0; i < 20; i++) {
            await new Promise(function(r) { setTimeout(r, 250); });
            tgUser = getTelegramUser();
            if (tgUser && tgUser.id) break;
        }
    }
    if (!tgUser || !tgUser.id) {
        var ug2 = document.getElementById('user-greeting');
        if (ug2) ug2.innerHTML = 'Error loading user. <a href="javascript:location.reload()" style="color:#FF8C00;text-decoration:underline;">Tap to retry</a>';
        return;
    }

    var uid = tgUser.id;
    try {
        // Server-verified player session: validates initData, creates/refreshes the
        // user doc server-side, and issues a short-lived player token used on all writes.
        var authData = await bootstrapPlayerToken();
        if (authData && authData.user) {
            currentUser = { id: authData.user.id, ...authData.user };
            updateAllDisplays();
            listenToUserData();
            startStatsListener();
            if (!currentUser.phone && !currentUser.registered) showRegistration();
            return;
        }
        // Fallback read path for already-provisioned users (legacy / dev).
        var userDoc = await db.collection('users').doc(String(uid)).get();
        if (userDoc.exists) {
            currentUser = { id: uid, ...userDoc.data() };
        } else {
            var newUser = {
                user_id: uid,
                first_name: tgUser.first_name || 'Player',
                username: tgUser.username || 'player' + uid,
                phone: '', balance: 0, play_wallet: 0, bonus: 0,
                total_games: 0, wins: 0, losses: 0, is_playing: false,
                created_at: firebase.firestore.FieldValue.serverTimestamp(),
                updated_at: firebase.firestore.FieldValue.serverTimestamp()
            };
            await db.collection('users').doc(String(uid)).set(newUser);
            currentUser = { id: uid, ...newUser };
        }
        updateAllDisplays();
        listenToUserData();
        startStatsListener();
        if (!currentUser.phone && !currentUser.registered) showRegistration();
    } catch (err) {
        console.error('Error initializing user:', err);
        var ug3 = document.getElementById('user-greeting');
        if (ug3) ug3.textContent = 'Error: ' + err.message;
    }
}

function showRegistration() {
    if (!currentUser) return;
    var rn = document.getElementById('regName');
    var rp = document.getElementById('regPhone');
    var rm = document.getElementById('registerModal');
    if (rn) rn.value = currentUser.first_name || '';
    if (rp) rp.value = currentUser.phone || '';
    if (rm) rm.classList.remove('hidden');
}

async function submitRegistration() {
    var rn = document.getElementById('regName');
    var rp = document.getElementById('regPhone');
    var name = rn ? rn.value.trim() : '';
    var phone = rp ? rp.value.trim() : '';
    if (!name) { showToast('Please enter your name'); return; }
    if (!phone || !phone.startsWith('+251')) { showToast('Enter valid phone (+251...)'); return; }
    try {
        await db.collection('users').doc(String(currentUser.id)).update({
            first_name: name, phone: phone, registered: true,
            updated_at: firebase.firestore.FieldValue.serverTimestamp()
        });
        currentUser.first_name = name;
        currentUser.phone = phone;
        updateAllDisplays();
        var rm = document.getElementById('registerModal');
        if (rm) rm.classList.add('hidden');
        showToast('Profile complete!');
    } catch (err) { showToast('Error saving profile.'); }
}

function listenToUserData() {
    if (userUnsubscribe) userUnsubscribe();
    userUnsubscribe = db.collection('users').doc(String(currentUser.id)).onSnapshot(function(doc) {
        if (doc.exists) { currentUser = { id: currentUser.id, ...doc.data() }; updateAllDisplays(); }
    });
}

function startStatsListener() {
    if (statsUnsubscribe) statsUnsubscribe();
    statsUnsubscribe = db.collection('rounds').where('status', 'in', ['selecting', 'playing']).onSnapshot(function(snap) {
        var totalCartelas = 0;
        snap.forEach(function(doc) { totalCartelas += (doc.data().player_count || 0); });
        var sp = document.getElementById('stat-players');
        if (sp) sp.textContent = totalCartelas;
    });
    function refreshCompletedStats() {
        var today = new Date(); today.setHours(0, 0, 0, 0);
        db.collection('rounds').where('status', '==', 'completed').get().then(function(snap) {
            var count = 0;
            var winners = 0;
            snap.forEach(function(doc) {
                var d = doc.data();
                if ((d.player_count || 0) > 0) count++;
                if (d.winners && d.winners.length > 0) {
                    var ca = d.completed_at;
                    if (ca) {
                        var dt = ca.toDate ? ca.toDate() : new Date(ca);
                        if (dt >= today) winners += d.winners.length;
                    }
                }
            });
            var sg = document.getElementById('stat-games');
            if (sg) sg.textContent = count;
            var sw = document.getElementById('stat-winners');
            if (sw) sw.textContent = winners;
        }).catch(function() {});
    }
    refreshCompletedStats();
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = setInterval(refreshCompletedStats, 10000);
}
