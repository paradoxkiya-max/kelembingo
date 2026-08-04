// ==================== WALLET ====================
var _depositConfig = {
    phone: '0911000000',
    pending_count: 0,
    pending_limit: 3
};

function openDepositBot() {
    requestDeposit();
}

function _setDepositStep(step) {
    var stepOne = document.getElementById('depositStepOne');
    var stepTwo = document.getElementById('depositStepTwo');
    if (stepOne) stepOne.classList.toggle('hidden', step !== 1);
    if (stepTwo) stepTwo.classList.toggle('hidden', step !== 2);
}

function _resetDepositModal() {
    var amountEl = document.getElementById('depositAmount');
    var txnEl = document.getElementById('depositTransactionId');
    var nameEl = document.getElementById('depositTelebirrName');
    if (amountEl) amountEl.value = '';
    if (txnEl) txnEl.value = '';
    if (nameEl) nameEl.value = (currentUser && (currentUser.telebirr_name || currentUser.first_name)) || '';
    _setDepositStep(1);
}

function hideDepositModal() {
    hideScreen('depositModal');
    _resetDepositModal();
}

async function requestDeposit() {
    if (!currentUser) { showToast('Loading user data...'); return; }
    showLoading('Preparing deposit...');
    try {
        var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        var res = await fetch(apiBase + '/api/deposits/config/' + encodeURIComponent(currentUser.id));
        var data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || 'Could not load deposit settings');
        }

        _depositConfig.phone = data.phone || _depositConfig.phone;
        _depositConfig.pending_count = data.pending_count || 0;
        _depositConfig.pending_limit = data.pending_limit || 3;

        if (!data.ok) {
            var depositErrors = {
                too_many_pending: 'You already have too many pending deposits. Wait for review first.',
                admin_offline: 'Admin is offline. Please try again later.'
            };
            showToast(depositErrors[data.error] || 'Deposit is not available right now');
            return;
        }

        var pendingEl = document.getElementById('depositPendingCount');
        var phoneEl = document.getElementById('depositTargetPhone');
        var nameEl = document.getElementById('depositTelebirrName');
        if (pendingEl) pendingEl.textContent = _depositConfig.pending_count + ' / ' + _depositConfig.pending_limit;
        if (phoneEl) phoneEl.textContent = _depositConfig.phone;
        if (nameEl) nameEl.value = (currentUser.telebirr_name || currentUser.first_name || '');
        _setDepositStep(1);
        document.getElementById('depositModal').classList.remove('hidden');
    } catch (err) {
        showToast('Error: ' + err.message);
    } finally {
        hideLoading();
    }
}

function continueDepositStep() {
    var name = document.getElementById('depositTelebirrName').value.trim();
    var amount = parseFloat(document.getElementById('depositAmount').value);
    if (!name) { showToast('Enter TeleBirr full name'); return; }
    if (!amount || amount < 10) { showToast('Minimum deposit is 10 ETB'); return; }

    var amountEl = document.getElementById('depositSummaryAmount');
    var phoneEl = document.getElementById('depositTargetPhone');
    if (amountEl) amountEl.textContent = amount + ' ETB';
    if (phoneEl) phoneEl.textContent = _depositConfig.phone || '0911000000';
    _setDepositStep(2);
}

function backDepositStep() {
    _setDepositStep(1);
}

async function submitDeposit() {
    var name = document.getElementById('depositTelebirrName').value.trim();
    var amount = parseFloat(document.getElementById('depositAmount').value);
    var transactionId = document.getElementById('depositTransactionId').value.trim();

    if (!name) { showToast('Enter TeleBirr full name'); return; }
    if (!amount || amount < 10) { showToast('Minimum deposit is 10 ETB'); return; }
    if (!transactionId || transactionId.length < 3) { showToast('Enter a valid transaction number'); return; }

    showLoading('Submitting deposit...');
    try {
        var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        var res = await fetch(apiBase + '/api/deposits/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser.id,
                telebirr_name: name,
                amount: amount,
                transaction_id: transactionId
            })
        });
        var data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || 'Could not submit deposit');
        }

        hideDepositModal();
        showToast('Deposit request submitted!');
        if (typeof loadWalletTransactions === 'function') loadWalletTransactions();
    } catch (err) {
        showToast('Error: ' + err.message);
    } finally {
        hideLoading();
    }
}

function requestWithdrawal() {
    const bal = currentUser ? currentUser.play_wallet || 0 : 0;
    document.getElementById('withdraw-available').textContent = bal + ' ETB';
    document.getElementById('withdrawModal').classList.remove('hidden');
}

async function submitWithdrawal() {
    const amount = parseInt(document.getElementById('withdrawAmount').value);
    const phone = document.getElementById('withdrawTelebirr').value.trim();
    const name = document.getElementById('withdrawTelebirrName').value.trim();
    if (!amount || amount < 50) { showToast('Minimum withdrawal: 50 ETB'); return; }
    if (!phone) { showToast('Enter phone number'); return; }
    try {
        const apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        const valRes = await fetch(apiBase + '/api/validate-withdrawal/' + currentUser.id + '?amount=' + amount);
        const val = await valRes.json();
        if (!val.ok) {
            const errorMessages = {
                below_min: 'Minimum withdrawal is ' + (val.min || 50) + ' ETB',
                insufficient: 'Insufficient balance! Your balance: ' + (val.balance || 0) + ' ETB',
                above_max: 'Maximum withdrawal is ' + (val.max || 50000) + ' ETB',
                no_phone: 'Please register with your phone number first',
                account_new: 'Your account is too new. Wait 24 hours after registration.',
                deposit_required: 'Minimum initial deposit of ' + (val.min_deposit || 50) + ' ETB required before withdrawing.',
                pending_exists: 'You already have a pending withdrawal. Wait for it to be processed.',
                daily_limit: 'Daily withdrawal limit reached (' + (val.limit || 3) + '/day). Try again tomorrow.',
                cooldown: 'Please wait ' + (val.minutes || 0) + ' minutes before another withdrawal.',
                invalid_amount: 'Please enter a valid withdrawal amount.',
                not_registered: 'User account not found. Please register first.',
                system_error: 'Server error validating withdrawal. Try again.'
            };
            showToast(errorMessages[val.error] || 'Withdrawal not allowed (' + (val.error || 'error') + ')');
            return;
        }
        var batch = db.batch();
        var userRef = db.collection('users').doc(String(currentUser.id));
        batch.update(userRef, {
            play_wallet: firebase.firestore.FieldValue.increment(-amount),
            updated_at: firebase.firestore.FieldValue.serverTimestamp()
        });
        var withdrawRef = db.collection('withdrawals').doc();
        batch.set(withdrawRef, {
            userId: String(currentUser.id),
            firstName: currentUser.first_name,
            username: currentUser.username,
            amount: amount,
            phone: phone,
            telebirrName: name,
            status: 'pending',
            createdAt: firebase.firestore.FieldValue.serverTimestamp()
        });
        await batch.commit();
        try {
            await fetch(apiBase + '/api/admin/withdrawals/notify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    withdrawal_id: withdrawRef.id,
                    user_id: currentUser.id,
                    first_name: currentUser.first_name,
                    username: currentUser.username,
                    amount: amount,
                    phone: phone,
                    telebirr_name: name
                })
            });
        } catch (e) { console.warn('Admin notification failed:', e); }
        hideScreen('withdrawModal');
        showToast('Withdrawal request submitted!');
    } catch (err) { showToast('Error: ' + err.message); }
}

function showTransferModal() { document.getElementById('transfer-modal').classList.remove('hidden'); }
function hideTransferModal() { document.getElementById('transfer-modal').classList.add('hidden'); }

var _txnCache = null;
async function loadWalletTransactions() {
    if (!currentUser) return;
    var container = document.getElementById('transaction-list');
    if (!container) return;

    container.innerHTML = '<div class="glass rounded-xl p-4 text-center"><p class="text-white/30 text-sm">Loading transactions...</p></div>';
    try {
        var uid = String(currentUser.id);
        var results = await Promise.all([
            db.collection('deposits').where('userId', '==', uid).get(),
            db.collection('withdrawals').where('userId', '==', uid).get()
        ]);

        if (!results[0].docs.length && !results[1].docs.length) {
            container.innerHTML = '<div class="glass rounded-xl p-4 text-center"><p class="text-white/30 text-sm">No transactions yet</p></div>';
            return;
        }

        var items = [];
        results[0].forEach(function(doc) {
            var d = doc.data();
            items.push({
                id: doc.id, type: 'deposit', amount: d.amount || 0,
                status: d.status || 'pending', createdAt: d.createdAt, label: 'Deposit'
            });
        });
        results[1].forEach(function(doc) {
            var d = doc.data();
            items.push({
                id: doc.id, type: 'withdraw', amount: d.amount || 0,
                status: d.status || 'pending', createdAt: d.createdAt, label: 'Withdraw'
            });
        });

        items.sort(function(a, b) {
            function toTime(v) {
                if (!v) return 0;
                if (v.toDate) return v.toDate().getTime();
                if (v._iso) return new Date(v._iso).getTime();
                return new Date(v).getTime() || 0;
            }
            return toTime(b.createdAt) - toTime(a.createdAt);
        });

        container.innerHTML = items.slice(0, 8).map(function(item) {
            var color = item.type === 'deposit' ? 'text-bingo-green' : 'text-bingo-orange';
            var badge = item.status === 'approved' ? 'text-bingo-green' : (item.status === 'rejected' ? 'text-bingo-red' : 'text-bingo-yellow');
            return '<div class="glass rounded-xl p-4 flex items-center justify-between gap-3">' +
                '<div><div class="text-sm font-semibold text-white">' + item.label + '</div>' +
                '<div class="text-xs ' + badge + ' uppercase">' + item.status + '</div></div>' +
                '<div class="text-right"><div class="text-sm font-bold ' + color + '">' + item.amount + ' ETB</div>' +
                '<div class="text-[11px] text-white/35">#' + item.id.slice(0, 6) + '</div></div></div>';
        }).join('');
    } catch (err) {
        container.innerHTML = '<div class="glass rounded-xl p-4 text-center"><p class="text-red-400 text-sm">Could not load transactions</p></div>';
    }
}

async function transferFunds(direction) {
    showToast('Wallet system simplified — deposits & withdrawals use your play wallet directly. No transfer needed.');
    hideTransferModal();
    document.getElementById('transfer-amount').value = '';
}

document.addEventListener('pageLoaded', function(e) {
    if (e.detail.screen === 'wallet' && currentUser) {
        loadWalletTransactions();
    }
});
