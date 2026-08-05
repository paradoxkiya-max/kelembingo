// ==================== GAMES (ROUNDS) ====================
function renderGames() {
    var activeList = document.getElementById('gamesActiveList');
    var activeEmpty = document.getElementById('gamesActiveEmpty');
    var active = allRounds.filter(function (g) { return (g.status === 'selecting' || g.status === 'playing') && (g.player_count || 0) > 0; });

    if (active.length === 0) {
        activeList.innerHTML = '';
        activeEmpty.classList.remove('hidden');
    } else {
        activeEmpty.classList.add('hidden');
        activeList.innerHTML = active.map(function (g) {
            var id = g.id || '';
            var shortId = typeof id === 'string' ? id.substring(0, 8) : id;
            var statusDot = g.status === 'playing' ? 'bg-[#10B981] anim-live' : 'bg-[#FF8C00] anim-live';
            var calledCount = (g.called_numbers || []).length;
            var derash = g.derash || (Math.round((g.player_count || 0) * (g.stake || 10) * 0.75 * 10) / 10);

            var playerNames = [];
            if (g.players) {
                Object.keys(g.players).forEach(function (pid) {
                    var pname = g.players[pid];
                    if (pname && typeof pname === 'string') playerNames.push(pname);
                });
            }
            var playersDisplay = playerNames.length > 0 ? playerNames.slice(0, 3).join(', ') + (playerNames.length > 3 ? '...' : '') : (g.player_count || 0) + ' cartelas';

            return '<div class="glass rounded-xl p-4 hover:bg-white/[0.03] transition-all">' +
                '<div class="flex items-center justify-between mb-3">' +
                '<div class="flex items-center gap-3">' +
                '<span class="w-2.5 h-2.5 rounded-full ' + statusDot + '"></span>' +
                '<div>' +
                '<p class="text-sm font-semibold">Round #' + shortId + '</p>' +
                '<p class="text-xs text-gray-500">👥 ' + escHtml(playersDisplay) + '</p>' +
                '</div>' +
                '</div>' +
                '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full ' + (g.status === 'playing' ? 'bg-[#10B981]/20 text-[#10B981]' : 'bg-[#FF8C00]/20 text-[#FF8C00]') + '">' + g.status.toUpperCase() + '</span>' +
                '</div>' +
                '<div class="grid grid-cols-4 gap-2 mb-3">' +
                '<div class="text-center glass rounded-lg p-2"><p class="text-[10px] text-gray-500">Stake</p><p class="text-xs font-bold text-[#FF8C00]">' + (g.stake || 0) + ' ETB</p></div>' +
                '<div class="text-center glass rounded-lg p-2"><p class="text-[10px] text-gray-500">Called</p><p class="text-xs font-bold text-[#3B82F6]">' + calledCount + '/75</p></div>' +
                '<div class="text-center glass rounded-lg p-2"><p class="text-[10px] text-gray-500">Cartelas</p><p class="text-xs font-bold text-[#8B5CF6]">' + (g.player_count || 0) + '</p></div>' +
                '<div class="text-center glass rounded-lg p-2"><p class="text-[10px] text-gray-500">DERASH</p><p class="text-xs font-bold text-[#14B8A6]">' + derash + ' ETB</p></div>' +
                '</div>' +
                '</div>';
        }).join('');
    }

    var sorted = allRounds.slice().sort(function (a, b) {
        var ta = a.created_at ? (a.created_at.seconds || 0) : 0;
        var tb = b.created_at ? (b.created_at.seconds || 0) : 0;
        return tb - ta;
    });
    var completed = sorted.filter(function (g) { return g.status === 'completed' && (g.player_count || 0) > 0; });
    var histBody = document.getElementById('gamesHistoryTable');
    var histEmpty = document.getElementById('gamesHistoryEmpty');

    if (completed.length === 0) {
        histBody.innerHTML = '';
        histEmpty.classList.remove('hidden');
    } else {
        histEmpty.classList.add('hidden');
        histBody.innerHTML = completed.slice(0, 50).map(function (g) {
            var id = g.id || '';
            var shortId = typeof id === 'string' ? id.substring(0, 8) : id;
            var hasWinner = g.winners && g.winners.length > 0;
            var statusColor = hasWinner ? 'text-[#10B981] bg-[#10B981]/10' : 'text-gray-400 bg-white/5';
            var statusLabel = hasWinner ? 'won' : 'no winner';
            var stake = g.stake || 0;
            var players = g.player_count || 0;
            var derash = g.derash || Math.round(players * stake * 0.75 * 10) / 10;
            var created = fmtTime(g.completed_at || g.created_at);
            var winCartela = g.winning_cartela ? '#' + g.winning_cartela : '-';
            return '<tr class="tbl-row border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">' +
                '<td class="px-4 py-3 text-sm font-mono text-gray-400">#' + shortId + '</td>' +
                '<td class="px-4 py-3 text-sm text-center">' + players + '</td>' +
                '<td class="px-4 py-3 text-sm text-[#FF8C00] font-semibold text-center">' + stake + ' ETB</td>' +
                '<td class="px-4 py-3 text-sm text-[#A855F7] font-semibold text-center">' + derash + ' ETB</td>' +
                '<td class="px-4 py-3 text-sm text-[#10B981] text-center">' + escHtml(g.winner_name || (hasWinner ? g.winners[0].substring(0, 8) : '-')) + '</td>' +
                '<td class="px-4 py-3 text-sm text-[#FFD700] text-center font-mono">' + winCartela + '</td>' +
                '<td class="px-4 py-3"><span class="text-xs font-semibold px-2 py-1 rounded-full ' + statusColor + '">' + statusLabel + '</span></td>' +
                '<td class="px-4 py-3 text-xs text-gray-500">' + created + '</td>' +
                '<td class="px-4 py-3 text-right"><button onclick="requestDeleteRound(\'' + id + '\',\'' + shortId + '\')" class="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded bg-red-400/10 hover:bg-red-400/20">Delete</button></td>' +
                '</tr>';
        }).join('');
    }
}

function adminEndRound(roundId) {
    if (!confirm('End this round? No winner will be declared.')) return;
    api('POST', '/api/rounds/' + roundId + '/end', { winner_ids: [] })
        .then(function () {
            showToast('✅ Round ended successfully.', 'success');
        })
        .catch(function (e) {
            console.error(e);
            alert('Failed to end round: ' + e.message);
        });
}

function requestDeleteRound(roundId, shortId) {
    gameToDeleteId = roundId;
    document.getElementById('gameDeleteId').textContent = '#' + shortId;
    openModal('gameDeleteModal');
}

function confirmDeleteGame() {
    if (!gameToDeleteId) return;
    var gid = gameToDeleteId;
    gameToDeleteId = null;
    closeModal('gameDeleteModal');
    db.collection('rounds').doc(gid).delete()
        .then(function () { })
        .catch(function (e) { console.error(e); alert('Failed to delete round.'); });
}

function requestDeleteAllGames() {
    var completed = allRounds.filter(function (g) { return g.status === 'completed' && (g.player_count || 0) > 0; });
    document.getElementById('gameDeleteAllCount').textContent = completed.length;
    openModal('deleteAllGamesModal');
}

function confirmDeleteAllGames() {
    closeModal('deleteAllGamesModal');
    db.collection('rounds').where('status', '==', 'completed').get().then(function (snap) {
        if (snap.empty) return;
        var batch = db.batch();
        snap.forEach(function (doc) { batch.delete(doc.ref); });
        batch.commit().then(function () { });
    }).catch(function (e) { console.error(e); alert('Failed to delete rounds.'); });
}

function requestClearAllActiveGames() {
    db.collection('rounds').where('status', 'in', ['selecting', 'playing']).get().then(function (snap) {
        document.getElementById('clearActiveGamesCount').textContent = snap.size;
        openModal('clearAllActiveGamesModal');
    });
}

function confirmClearAllActiveGames() {
    closeModal('clearAllActiveGamesModal');
    db.collection('rounds').where('status', 'in', ['selecting', 'playing']).get().then(function (snap) {
        if (snap.empty) return;
        var count = 0;
        var total = snap.size;
        snap.forEach(function (doc) {
            doc.ref.update({ status: 'completed', winners: [], winner_name: 'No winner', prize_per_winner: 0, admin_profit: 0 })
                .then(function () {
                    count++;
                    if (count >= total) { }
                })
                .catch(function (e) { console.error(e); count++; });
        });
    }).catch(function (e) { console.error(e); alert('Failed to clear rounds.'); });
}

function deleteGame(gameId) {
    requestDeleteRound(gameId, gameId.substring(0, 8));
}
