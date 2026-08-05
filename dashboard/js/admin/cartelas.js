// ==================== CARTELA POOL ====================
var _cartelaPoolUnsubscribe = null;

function generateOneCartela() {
    var ranges = [{ min: 1, max: 15 }, { min: 16, max: 30 }, { min: 31, max: 45 }, { min: 46, max: 60 }, { min: 61, max: 75 }];
    var cartela = [];
    for (var col = 0; col < 5; col++) {
        var colNums = [];
        var avail = [];
        for (var n = ranges[col].min; n <= ranges[col].max; n++) avail.push(n);
        for (var row = 0; row < 5; row++) {
            if (col === 2 && row === 2) { colNums.push(0); continue; }
            var idx = Math.floor(Math.random() * avail.length);
            colNums.push(avail.splice(idx, 1)[0]);
        }
        cartela.push(colNums);
    }
    return cartela;
}

async function generateCartelaPool() {
    console.log('[CART-DBG] API_BASE:', API_BASE);
    
    try {
        var url = API_BASE + '/api/cartelas/generate';
        console.log('[CART-DBG] POST', url);
        var res = await fetch(url, { method: 'POST' });
        console.log('[CART-DBG] Status:', res.status);
        var raw = await res.text();
        console.log('[CART-DBG] Response:', raw.substring(0, 300));
        if (!raw) throw new Error('Empty response from server');
        var data = JSON.parse(raw);
        
        if (data.status === 'already_exists') {
            alert('Cartelas already exist (' + (data.count || 0) + ' cartelas).');
            return;
        }
        
        if (data.status === 'generating') {
            console.log('[CART-DBG] Generation started, polling for progress...');
            alert('Cartela generation started. Monitoring progress...');
            await _pollCartelaProgress();
            return;
        }
        
        alert('Generated 500 cartelas successfully!');
    } catch (e) {
        console.error('[CART-DBG] FAILED:', e.name, e.message);
        alert('Error generating cartelas: ' + e.message);
    }
}

async function _pollCartelaProgress() {
    var statusUrl = API_BASE + '/api/cartelas/status';
    var maxPolls = 150; // 5 minutes max (2s intervals)
    for (var i = 0; i < maxPolls; i++) {
        await new Promise(function (r) { setTimeout(r, 2000); });
        try {
            var res = await fetch(statusUrl);
            var raw = await res.text();
            if (!raw) continue;
            var status = JSON.parse(raw);
            console.log('[CART-DBG] Progress:', status.generated + '/' + status.total, 'status=' + status.status);
            
            if (status.status === 'done') {
                alert('Generated ' + (status.generated || 500) + ' cartelas successfully!');
                return;
            }
            if (status.status === 'error') {
                alert('Error generating cartelas: ' + (status.error || 'Unknown error'));
                return;
            }
            if (status.status === 'idle') {
                alert('Cartela generation completed!');
                return;
            }
            // Still generating - continue polling
        } catch (e) {
            console.warn('[CART-DBG] Poll error:', e.message);
        }
    }
    alert('Timed out waiting for cartela generation. Check server logs.');
}

function loadCartelaPool() {
    // Unsubscribe previous listener
    if (_cartelaPoolUnsubscribe) { _cartelaPoolUnsubscribe(); _cartelaPoolUnsubscribe = null; }

    _cartelaPoolUnsubscribe = db.collection('cartelas_master').orderBy('number').onSnapshot(function (snap) {
        var list = document.getElementById('cartelaPoolList');
        var empty = document.getElementById('cartelaPoolEmpty');
        if (!list || !empty) return;

        var items = [];
        snap.forEach(function (doc) {
            items.push({ id: doc.id, data: doc.data() });
        });
        document.getElementById('cartelaAvailableCount').textContent = items.length;
        document.getElementById('cartelaAssignedCount').textContent = 0;
        document.getElementById('cartelaUsedCount').textContent = 0;

        if (items.length === 0) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }
        empty.classList.add('hidden');
        list.innerHTML = items.map(function (item) {
            var d = item.data;
            var num = d.number || item.id;
            var flat = d.cartela || [];
            var mini = '<div class="grid grid-cols-5 gap-0.5 max-w-[120px]">';
            var hdrs = ['B', 'I', 'N', 'G', 'O'];
            var hcls = ['text-[#10B981]', 'text-[#3B82F6]', 'text-[#8B5CF6]', 'text-[#FF8C00]', 'text-[#14B8A6]'];
            for (var i = 0; i < 5; i++) mini += '<div class="' + hcls[i] + ' text-center text-[7px] font-bold">' + hdrs[i] + '</div>';
            for (var r = 0; r < 5; r++) {
                for (var c = 0; c < 5; c++) {
                    var v = (Array.isArray(flat[0]) ? flat[c][r] : flat[r * 5 + c]) || 0;
                    if (r === 2 && c === 2) mini += '<div class="bg-[#FF8C00]/20 text-[#FF8C00] text-center text-[7px] font-bold rounded">⭐</div>';
                    else mini += '<div class="bg-white/5 text-white/60 text-center text-[7px] font-bold rounded">' + v + '</div>';
                }
            }
            mini += '</div>';
            return '<div class="px-6 py-3 flex items-center justify-between hover:bg-white/[0.02]">' +
                '<div class="flex items-center gap-4">' +
                '<div class="text-sm font-mono text-gray-400">#' + num + '</div>' +
                mini +
                '</div>' +
                '<div class="flex items-center gap-2">' +
                '<span class="text-[10px] px-2 py-0.5 rounded-full bg-[#10B981]/10 text-[#10B981] font-semibold">Master</span>' +
                '</div>' +
                '</div>';
        }).join('');
    });
}

function stopCartelaPoolListener() {
    if (_cartelaPoolUnsubscribe) { _cartelaPoolUnsubscribe(); _cartelaPoolUnsubscribe = null; }
}
