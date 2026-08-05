// ==================== USER MANAGEMENT ====================
function renderUsersTable() {
    var search = (document.getElementById('userSearchInput').value || '').toLowerCase();
    var statusFilter = document.getElementById('userStatusFilter').value;

    var filtered = allUsers.filter(function (u) {
        var name = (u.first_name || '').toLowerCase();
        var uname = (u.username || '').toLowerCase();
        var uid = String(u.user_id || '').toLowerCase();
        var matchSearch = !search || name.indexOf(search) > -1 || uname.indexOf(search) > -1 || uid.indexOf(search) > -1;
        var matchStatus = statusFilter === 'all' || (u.status || 'active') === statusFilter;
        return matchSearch && matchStatus;
    });

    var totalPages = Math.max(1, Math.ceil(filtered.length / userPageSize));
    if (userPage > totalPages) userPage = totalPages;
    var start = (userPage - 1) * userPageSize;
    var pageItems = filtered.slice(start, start + userPageSize);

    var tbody = document.getElementById('usersTableBody');
    var emptyEl = document.getElementById('usersTableEmpty');
    if (!tbody) return;

    if (pageItems.length === 0) {
        tbody.innerHTML = '';
        emptyEl.classList.remove('hidden');
    } else {
        emptyEl.classList.add('hidden');
        tbody.innerHTML = pageItems.map(function (u) {
            var name = u.first_name || 'Unknown';
            var initial = name.charAt(0).toUpperCase();
            var uname = u.username ? '@' + u.username : '-';
            var uid = u.user_id || '-';
            var walletVal = typeof u.play_wallet === 'object' ? (u.play_wallet.value || 0) : (u.play_wallet || 0);
            var balance = Number(walletVal).toFixed(2);
            var games = u.total_games || u.games_played || 0;
            var wins = u.wins || 0;
            var status = u.status || 'active';
            var statusClass = status === 'active' ? 'bg-[#10B981]/10 text-[#10B981]' : (status === 'banned' ? 'bg-red-500/10 text-red-400' : 'bg-yellow-500/10 text-yellow-400');
            var colors = ['from-[#FF8C00] to-yellow-500', 'from-[#3B82F6] to-cyan-500', 'from-[#8B5CF6] to-pink-500', 'from-[#14B8A6] to-emerald-500', 'from-red-500 to-orange-500'];
            var color = colors[Math.abs(hashStr(uid)) % colors.length];
            var docId = u._docId || '';

            return '<tr class="tbl-row border-b border-white/[0.03]">' +
                '<td class="px-4 py-3"><div class="flex items-center gap-3">' +
                '<div class="w-9 h-9 rounded-lg bg-gradient-to-br ' + color + ' flex items-center justify-center text-sm font-bold">' + initial + '</div>' +
                '<div><p class="text-sm font-semibold">' + escHtml(name) + '</p><p class="text-[10px] text-gray-500">' + escHtml(uname) + '</p></div>' +
                '</div></td>' +
                '<td class="px-4 py-3 text-sm text-gray-400 font-mono">' + escHtml(String(uid)) + '</td>' +
                '<td class="px-4 py-3 text-sm text-[#10B981] font-semibold">' + balance + ' ETB</td>' +
                '<td class="px-4 py-3 text-sm font-medium">' + games + '</td>' +
                '<td class="px-4 py-3 text-sm font-medium text-[#FF8C00]">' + wins + '</td>' +
                '<td class="px-4 py-3"><span class="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full ' + statusClass + '"><span class="w-1.5 h-1.5 rounded-full bg-current"></span>' + status + '</span></td>' +
                '<td class="px-4 py-3"><div class="flex items-center gap-1">' +
                '<button onclick="viewUser(\'' + escHtml(docId) + '\')" class="p-1.5 rounded-lg hover:bg-white/5 transition-all" title="View"><span class="text-sm">👁️</span></button>' +
                '<button onclick="openEditBalance(\'' + escHtml(docId) + '\',\'' + escHtml(name) + '\',' + (Number(walletVal) || 0) + ')" class="p-1.5 rounded-lg hover:bg-white/5 transition-all" title="Edit Balance"><span class="text-sm">💰</span></button>' +
                '<button onclick="toggleBanUser(\'' + escHtml(docId) + '\',\'' + escHtml(status) + '\')" class="p-1.5 rounded-lg hover:bg-red-500/10 transition-all" title="Ban/Unban"><span class="text-sm">' + (status === 'banned' ? '✅' : '🚫') + '</span></button>' +
                '<button onclick="requestDeleteUser(\'' + escHtml(docId) + '\',\'' + escHtml(name) + '\')" class="p-1.5 rounded-lg hover:bg-red-500/10 transition-all" title="Delete"><span class="text-sm">🗑️</span></button>' +
                '</div></td>' +
                '</tr>';
        }).join('');
    }

    document.getElementById('usersPaginationInfo').textContent = 'Showing ' + (filtered.length > 0 ? start + 1 : 0) + '-' + Math.min(start + userPageSize, filtered.length) + ' of ' + filtered.length + ' users';

    var pgDiv = document.getElementById('usersPaginationControls');
    var pgHtml = '';
    pgHtml += '<button onclick="goUserPage(' + (userPage - 1) + ')" class="px-3 py-1.5 rounded-lg glass text-xs text-gray-400 hover:text-white transition-all ' + (userPage <= 1 ? 'opacity-30 pointer-events-none' : '') + '">&laquo;</button>';
    for (var i = 1; i <= totalPages && i <= 7; i++) {
        pgHtml += '<button onclick="goUserPage(' + i + ')" class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ' + (i === userPage ? 'bg-[#FF8C00] text-white' : 'glass text-gray-400 hover:text-white') + '">' + i + '</button>';
    }
    if (totalPages > 7) pgHtml += '<span class="px-2 text-xs text-gray-500">...</span><button onclick="goUserPage(' + totalPages + ')" class="px-3 py-1.5 rounded-lg glass text-xs text-gray-400 hover:text-white transition-all">' + totalPages + '</button>';
    pgHtml += '<button onclick="goUserPage(' + (userPage + 1) + ')" class="px-3 py-1.5 rounded-lg glass text-xs text-gray-400 hover:text-white transition-all ' + (userPage >= totalPages ? 'opacity-30 pointer-events-none' : '') + '">&raquo;</button>';
    pgDiv.innerHTML = pgHtml;
}

function filterUsers() { userPage = 1; renderUsersTable(); }
function goUserPage(p) { userPage = p; renderUsersTable(); }

function viewUser(docId) {
    var u = allUsers.find(function (x) { return x._docId === docId; });
    if (!u) return;
    var content = document.getElementById('userDetailsContent');
    var name = u.first_name || 'Unknown';
    var games = u.total_games || u.games_played || 0;
    var wins = u.wins || 0;
    var winRate = games > 0 ? ((wins / games) * 100).toFixed(1) : '0.0';
    var bal = typeof u.play_wallet === 'object' ? Number(u.play_wallet.value || 0) : Number(u.play_wallet || 0);
    content.innerHTML =
        '<div class="flex items-center gap-4 mb-4">' +
        '<div class="w-14 h-14 rounded-xl bg-gradient-to-br from-[#8B5CF6] to-[#3B82F6] flex items-center justify-center text-xl font-bold">' + name.charAt(0).toUpperCase() + '</div>' +
        '<div><p class="text-lg font-bold">' + escHtml(name) + '</p><p class="text-sm text-gray-400">@' + escHtml(u.username || 'no_username') + '</p></div>' +
        '</div>' +
        '<div class="grid grid-cols-2 gap-3">' +
        '<div class="glass rounded-xl p-3 text-center"><p class="text-lg font-bold text-[#10B981]">' + bal.toFixed(2) + '</p><p class="text-[10px] text-gray-500">Balance (ETB)</p></div>' +
        '<div class="glass rounded-xl p-3 text-center"><p class="text-lg font-bold text-[#3B82F6]">' + games + '</p><p class="text-[10px] text-gray-500">Games Played</p></div>' +
        '<div class="glass rounded-xl p-3 text-center"><p class="text-lg font-bold text-[#FF8C00]">' + wins + '</p><p class="text-[10px] text-gray-500">Wins</p></div>' +
        '<div class="glass rounded-xl p-3 text-center"><p class="text-lg font-bold text-[#8B5CF6]">' + winRate + '%</p><p class="text-[10px] text-gray-500">Win Rate</p></div>' +
        '</div>' +
        '<div class="border-t border-white/5 pt-4 mt-2 space-y-2 text-sm">' +
        '<div class="flex justify-between"><span class="text-gray-400">Telegram ID</span><span class="font-mono">' + escHtml(String(u.user_id || '-')) + '</span></div>' +
        '<div class="flex justify-between"><span class="text-gray-400">Status</span><span class="' + ((u.status || 'active') === 'active' ? 'text-[#10B981]' : 'text-red-400') + '">' + (u.status || 'active') + '</span></div>' +
        '<div class="flex justify-between"><span class="text-gray-400">Registered</span><span>' + fmtTime(u.created_at || u.join_date) + '</span></div>' +
        '<div class="flex justify-between"><span class="text-gray-400">Currently Playing</span><span>' + (u.is_playing ? 'Yes' : 'No') + '</span></div>' +
        '</div>';
    openModal('userDetailsModal');
}

function openEditBalance(docId, name, balance) {
    editingUserId = docId;
    var safeBal = (typeof balance === 'number') ? balance : (typeof balance === 'object' && balance ? Number(balance.value || 0) : Number(balance || 0));
    if (isNaN(safeBal)) safeBal = 0;
    document.getElementById('editBalanceUser').textContent = name;
    document.getElementById('editBalanceCurrent').textContent = safeBal.toFixed(2) + ' ETB';
    document.getElementById('editBalanceInput').value = safeBal;
    openModal('editBalanceModal');
}

function saveEditBalance() {
    if (!editingUserId) return;
    var newBal = parseFloat(document.getElementById('editBalanceInput').value);
    if (isNaN(newBal)) {
        alert('Please enter a valid number');
        return;
    }
    db.collection('users').doc(editingUserId).update({ play_wallet: newBal })
        .then(function () {
            closeModal('editBalanceModal');
            editingUserId = null;
        })
        .catch(function (e) {
            console.error('Error updating balance:', e);
            alert('Failed to update balance');
        });
}

function toggleBanUser(docId, currentStatus) {
    var newStatus = currentStatus === 'banned' ? 'active' : 'banned';
    db.collection('users').doc(docId).update({ status: newStatus })
        .catch(function (e) { console.error('Error toggling ban:', e); alert('Failed to update status'); });
}

function requestDeleteUser(docId, name) {
    deleteUserId = docId;
    document.getElementById('deleteUserName').textContent = name;
    openModal('deleteConfirmModal');
}

function confirmDeleteUser() {
    if (!deleteUserId) return;
    db.collection('users').doc(deleteUserId).delete()
        .then(function () {
            closeModal('deleteConfirmModal');
            deleteUserId = null;
        })
        .catch(function (e) { console.error('Error deleting user:', e); alert('Failed to delete user'); });
}

function addAdmin() {
    var displayName = document.getElementById('addAdminDisplayName').value.trim();
    var username = document.getElementById('addAdminUsername').value.trim();
    var password = document.getElementById('addAdminPassword').value.trim();
    var role = document.getElementById('addAdminRole').value;
    var msgEl = document.getElementById('addAdminMsg');

    if (!displayName || !username || !password) {
        msgEl.textContent = 'All fields are required';
        msgEl.className = 'text-sm rounded-xl px-4 py-3 bg-red-500/10 text-red-400 border border-red-500/20';
        msgEl.classList.remove('hidden');
        return;
    }

    db.collection('admins').where('username', '==', username).get()
        .then(function (snap) {
            if (!snap.empty) {
                msgEl.textContent = 'Username already exists';
                msgEl.className = 'text-sm rounded-xl px-4 py-3 bg-red-500/10 text-red-400 border border-red-500/20';
                msgEl.classList.remove('hidden');
                return;
            }
            return db.collection('admins').add({
                displayName: displayName,
                username: username,
                password: password,
                role: role,
                isActive: true,
                createdAt: firebase.firestore.FieldValue.serverTimestamp()
            });
        })
        .then(function () {
            if (msgEl.classList.contains('hidden') || !msgEl.textContent.includes('exists')) {
                msgEl.textContent = 'Admin created successfully!';
                msgEl.className = 'text-sm rounded-xl px-4 py-3 bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/20';
                msgEl.classList.remove('hidden');
                document.getElementById('addAdminDisplayName').value = '';
                document.getElementById('addAdminUsername').value = '';
                document.getElementById('addAdminPassword').value = '';
                setTimeout(function () { closeModal('addAdminModal'); msgEl.classList.add('hidden'); }, 1500);
            }
        })
        .catch(function (e) {
            console.error('Error adding admin:', e);
            msgEl.textContent = 'Error: ' + e.message;
            msgEl.className = 'text-sm rounded-xl px-4 py-3 bg-red-500/10 text-red-400 border border-red-500/20';
            msgEl.classList.remove('hidden');
        });
}
