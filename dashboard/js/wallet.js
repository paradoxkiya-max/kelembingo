// ==================== WALLET ====================
var _depositConfig = {
    phone: '0911000000',
    pending_count: 0,
    pending_limit: 3
};
var _depositConfigInFlight = null;
var _depositSubmitInFlight = false;
var _withdrawSubmitInFlight = false;
var _withdrawalRequestKey = null;

function _clientIdempotencyKey(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return prefix + ':' + window.crypto.randomUUID();
    }
    return prefix + ':' + Date.now() + ':' + Math.random().toString(36).slice(2);
}

function _setWalletButtonBusy(id, busy, busyLabel) {
    var button = document.getElementById(id);
    if (!button) return;
    if (busy) {
        if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent;
        button.disabled = true;
        button.textContent = busyLabel;
        button.style.opacity = '0.65';
    } else {
        button.disabled = false;
        button.textContent = button.dataset.defaultLabel || button.textContent;
        button.style.opacity = '';
    }
}

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
    if (!document.getElementById('depositPendingCount') && window.PageLoader) {
        await PageLoader.loadComponent('depositModal', 'deposit-modal.html');
    }
    if (_depositConfigInFlight) return _depositConfigInFlight;
    _depositConfigInFlight = (async function() {
    showLoading('Preparing deposit...');
    try {
        var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        var res;
        if (window.playerApi) {
            res = await window.playerApi('GET', '/api/deposits/config/' + encodeURIComponent(currentUser.id));
        } else {
            res = await fetch(apiBase + '/api/deposits/config/' + encodeURIComponent(currentUser.id));
        }
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
        _depositConfigInFlight = null;
    }
    })();
    return _depositConfigInFlight;
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
    if (_depositSubmitInFlight) return;
    var name = document.getElementById('depositTelebirrName').value.trim();
    var amount = parseFloat(document.getElementById('depositAmount').value);
    var transactionId = document.getElementById('depositTransactionId').value.trim();

    if (!name) { showToast('Enter TeleBirr full name'); return; }
    if (!amount || amount < 10) { showToast('Minimum deposit is 10 ETB'); return; }
    if (!transactionId || transactionId.length < 3) { showToast('Enter a valid transaction number'); return; }

    _depositSubmitInFlight = true;
    _setWalletButtonBusy('deposit-submit', true, 'Submitting...');
    showLoading('Submitting deposit...');
    try {
        var apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        var res;
        if (window.playerApi) {
            res = await window.playerApi('POST', '/api/deposits/submit', {
                user_id: currentUser.id,
                telebirr_name: name,
                amount: amount,
                transaction_id: transactionId
            });
        } else {
            res = await fetch(apiBase + '/api/deposits/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUser.id,
                    telebirr_name: name,
                    amount: amount,
                    transaction_id: transactionId
                })
            });
        }
        var data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || 'Could not submit deposit');
        }

        hideDepositModal();
        _txnCache = null;
        _txnCacheAt = 0;
        showToast('Deposit request submitted!');
        if (typeof loadWalletTransactions === 'function') loadWalletTransactions();
    } catch (err) {
        showToast('Error: ' + err.message);
    } finally {
        hideLoading();
        _setWalletButtonBusy('deposit-submit', false);
        _depositSubmitInFlight = false;
    }
}

async function requestWithdrawal() {
    if (!currentUser) { showToast('Loading user data...'); return; }
    if (!document.getElementById('withdrawAmount') && window.PageLoader) {
        await PageLoader.loadComponent('withdrawModal', 'withdraw-modal.html');
    }
    const bal = currentUser.play_wallet || 0;
    document.getElementById('withdraw-available').textContent = bal + ' ETB';
    var phoneEl = document.getElementById('withdrawTelebirr');
    var nameEl = document.getElementById('withdrawTelebirrName');
    if (phoneEl && !phoneEl.value) phoneEl.value = currentUser.phone || '';
    if (nameEl && !nameEl.value) nameEl.value = currentUser.telebirr_name || currentUser.first_name || '';
    _withdrawalRequestKey = null;
    document.getElementById('withdrawModal').classList.remove('hidden');
}

async function submitWithdrawal() {
    if (_withdrawSubmitInFlight) return;
    const amount = parseFloat(document.getElementById('withdrawAmount').value);
    const phone = document.getElementById('withdrawTelebirr').value.trim();
    const name = document.getElementById('withdrawTelebirrName').value.trim();
    if (!amount || amount < 50) { showToast('Minimum withdrawal: 50 ETB'); return; }
    if (!phone) { showToast('Enter phone number'); return; }
    if (!name) { showToast('Enter your TeleBirr full name'); return; }
    _withdrawSubmitInFlight = true;
    _withdrawalRequestKey = _withdrawalRequestKey || _clientIdempotencyKey('withdrawal');
    _setWalletButtonBusy('withdraw-submit', true, 'Submitting...');
    showLoading('Submitting withdrawal...');
    try {
        const apiBase = window.BACKEND_URL || window.API_BASE || window.location.origin || (window.location.protocol + '//' + window.location.host);
        // The create endpoint performs the same validation again under the
        // authoritative account lock; one request avoids a slow validation/create
        // race and keeps the idempotency key attached to the money operation.
        // Server-side creation: wallet decrement + withdrawal doc + admin notify all
        // happen atomically on the backend. No more client-side play_wallet writes.
        var res;
        showLoading('Submitting withdrawal...');
        if (window.playerApi) {
            res = await window.playerApi('POST', '/api/withdrawals/create', {
                amount: amount,
                phone: phone,
                telebirr_name: name
            }, { 'X-Idempotency-Key': _withdrawalRequestKey });
        } else {
            res = await fetch(apiBase + '/api/withdrawals/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Idempotency-Key': _withdrawalRequestKey },
                body: JSON.stringify({ amount: amount, phone: phone, telebirr_name: name })
            });
        }
        var data = await res.json();
        if (!res.ok || data.error || !data.ok) {
            const createMessages = {
                below_min: 'Minimum withdrawal: ' + (data.min || 50) + ' ETB.',
                insufficient: 'Insufficient balance for this withdrawal.',
                above_max: 'Withdrawal exceeds the allowed maximum.',
                no_phone: 'Please register with your phone number first.',
                no_name: 'Enter your TeleBirr full name.',
                account_new: 'Your account is too new. Wait 24 hours after registration.',
                deposit_required: 'A qualifying deposit is required before withdrawing.',
                pending_exists: 'You already have a pending withdrawal.',
                daily_limit: 'Daily withdrawal limit reached.',
                cooldown: 'Please wait before another withdrawal.',
                invalid_amount: 'Please enter a valid withdrawal amount.',
                system_error: 'Server error validating withdrawal. Try again.'
            };
            showToast(createMessages[data.error] || data.detail || 'Could not submit withdrawal');
            if (data.error && data.error !== 'system_error') _withdrawalRequestKey = null;
            return;
        }
        hideScreen('withdrawModal');
        _withdrawalRequestKey = null;
        _txnCache = null;
        _txnCacheAt = 0;
        showToast('Withdrawal request submitted!');
        if (typeof loadWalletTransactions === 'function') loadWalletTransactions();
    } catch (err) { showToast('Error: ' + err.message); }
    finally {
        hideLoading();
        _setWalletButtonBusy('withdraw-submit', false);
        _withdrawSubmitInFlight = false;
    }
}

function showTransferModal() { document.getElementById('transfer-modal').classList.remove('hidden'); }
function hideTransferModal() { document.getElementById('transfer-modal').classList.add('hidden'); }

var _txnCache = null;
var _txnCacheAt = 0;
async function loadWalletTransactions() {
    if (!currentUser) return;
    var container = document.getElementById('transaction-list');
    if (!container) return;
    if (_txnCache && Date.now() - _txnCacheAt < 15000) {
        container.innerHTML = _txnCache;
        return;
    }

    container.innerHTML = '<div class="glass rounded-xl p-4 text-center"><p class="text-white/30 text-sm">Loading transactions...</p></div>';
    try {
        var uid = String(currentUser.id);
        var results = await Promise.all([
            db.collection('deposits').where('userId', '==', uid).orderBy('createdAt', 'desc').limit(20).get(),
            db.collection('withdrawals').where('userId', '==', uid).orderBy('createdAt', 'desc').limit(20).get()
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
        _txnCache = container.innerHTML;
        _txnCacheAt = Date.now();
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
