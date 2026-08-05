// ==================== HISTORY ====================
function _fmtDate(ts) {
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

function _fmtDateTime(ts) {
    if (!ts) return '';
    try {
        var d;
        if (ts.toDate) { d = ts.toDate(); }
        else if (ts.seconds) { d = new Date(ts.seconds * 1000); }
        else if (typeof ts === 'string' || typeof ts === 'number') { d = new Date(ts); }
        else { return ''; }
        if (isNaN(d.getTime())) return '';
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ''; }
}

async function loadHistory() {
    if (!currentUser) return;
    
    var list = document.getElementById('history-list');
    var loading = document.getElementById('history-loading');
    var empty = document.getElementById('history-empty');
    
    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');
    
    try {
        var winnerSnap = await db.collection('rounds')
            .where('status', '==', 'completed')
            .limit(50).get();
        
        if (loading) loading.classList.add('hidden');
        
        var allRounds = [];
        winnerSnap.forEach(function(doc) {
            allRounds.push({ id: doc.id, data: doc.data() });
        });

        allRounds.sort(function(a, b) {
            var da = a.data.completed_at || a.data.created_at;
            var db2 = b.data.completed_at || b.data.created_at;
            var ta = da && da.toDate ? da.toDate().getTime() : (da && da.seconds ? da.seconds * 1000 : (da ? new Date(da).getTime() : 0));
            var tb = db2 && db2.toDate ? db2.toDate().getTime() : (db2 && db2.seconds ? db2.seconds * 1000 : (db2 ? new Date(db2).getTime() : 0));
            return tb - ta;
        });
        
        if (!list) return;
        list.innerHTML = '';
        
        var recentWinners = [];
        allRounds.forEach(function(item) {
            var d = item.data;
            if (d.winners && d.winners.length > 0 && d.winner_name && d.winner_name !== 'No players') {
                var date = _fmtDate(d.completed_at);
                if (recentWinners.length < 3) {
                    recentWinners.push({
                        name: d.winner_name,
                        prize: Math.round((d.prize_per_winner || 0) * 10) / 10,
                        date: date,
                        cartela: Array.isArray(d.winning_cartela) ? d.winning_cartela.join(', ') : (d.winning_cartela || '?'),
                        stake: d.stake || 10
                    });
                }
            }
        });
        
        if (recentWinners.length > 0) {
            var winnersHeader = document.createElement('div');
            winnersHeader.className = 'mb-3';
            winnersHeader.innerHTML = '<h3 class="text-sm font-bold text-amber-400 mb-2 flex items-center gap-2">' +
                '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>' +
                'Recent Winners</h3>';
            list.appendChild(winnersHeader);
            
            recentWinners.forEach(function(w) {
                var el = document.createElement('div');
                el.className = 'glass rounded-xl p-3 flex items-center justify-between';
                el.innerHTML = '<div class="flex items-center gap-3">' +
                    '<div class="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold" style="background: linear-gradient(135deg, #FFD700, #FF8C00); color: #1a1a2e;">&#127942;</div>' +
                    '<div>' +
                    '<div class="text-sm font-bold text-white">' + w.name + '</div>' +
                    '<div class="text-[10px] text-white/40">Cartela #' + w.cartela + ' &middot; ' + w.stake + ' ETB &middot; ' + w.date + '</div>' +
                    '</div>' +
                    '</div>' +
                    '<div class="text-right">' +
                    '<div class="text-sm font-bold text-bingo-green">' + w.prize + ' ETB</div>' +
                    '<div class="text-[10px] text-amber-400/60">Winner!</div>' +
                    '</div>';
                list.appendChild(el);
            });
            
            var divider = document.createElement('div');
            divider.className = 'border-t border-white/5 my-3';
            list.appendChild(divider);
        }
        
        var uidStr = String(currentUser.id);
        var myRounds = [];
        allRounds.forEach(function(item) {
            var d = item.data;
            var wasPlayer = d.players && d.players[uidStr];
            if (wasPlayer && (d.player_count || 0) > 0) myRounds.push({ id: item.id, data: d });
        });
        
        var myHeader = document.createElement('div');
        myHeader.className = 'mb-3 mt-4';
        myHeader.innerHTML = '<h3 class="text-sm font-bold text-white/60 mb-2">Your Games</h3>';
        list.appendChild(myHeader);

        if (myRounds.length > 0) {
            myRounds.forEach(function(item) {
                var d = item.data;
                var isWinner = (d.winners || []).includes(uidStr);
                var el = document.createElement('div');
                el.className = 'glass rounded-xl p-3 mb-2';
                var prize = isWinner ? (Math.round((d.prize_per_winner || 0) * 10) / 10) : 0;
                var stake = d.stake || 10;
                var date = _fmtDate(d.completed_at || d.created_at);
                el.innerHTML = '<div class="flex items-center justify-between mb-1">' +
                    '<span class="text-sm font-bold ' + (isWinner ? 'text-bingo-green' : 'text-red-400') + '">' + (isWinner ? '&#127942; Won!' : '&#10060; Lost') + '</span>' +
                    '<span class="text-xs text-white/40">' + stake + ' ETB &middot; ' + date + '</span>' +
                    '</div>' +
                    '<div class="flex items-center justify-between text-xs text-white/60">' +
                    '<span>Cartelas: ' + (d.player_count || 0) + '</span>' +
                    '<span>Derash: ' + prize + ' ETB</span>' +
                    '</div>';
                list.appendChild(el);
            });
        } else {
            var emptyPlayer = document.createElement('div');
            emptyPlayer.className = 'glass rounded-xl p-4 text-center text-white/40 text-xs my-2';
            emptyPlayer.textContent = 'No game history yet. Join a round to start playing!';
            list.appendChild(emptyPlayer);
        }
    } catch (err) {
        if (loading) loading.classList.add('hidden');
        console.error('History error:', err);
        if (empty) empty.classList.remove('hidden');
    }
}
