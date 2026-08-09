// ==================== DATA BACKUP ====================

function _backupStatCard(label, value, accent) {
    var color = accent || 'text-white';
    return '' +
        '<div class="bg-[#0D1117] border border-white/10 rounded-xl p-4 text-center">' +
        '<p class="text-xs text-gray-500 mb-1">' + escHtml(label) + '</p>' +
        '<p class="text-lg font-bold ' + color + ' truncate">' + escHtml(value) + '</p>' +
        '</div>';
}

function loadBackupStatus() {
    var box = document.getElementById('backupStatus');
    if (box) box.innerHTML = '<div class="text-center py-6 col-span-full text-gray-600 text-sm">Loading backup status…</div>';
    api('GET', '/api/admin/backup/status')
        .then(function (s) {
            if (!box) return;
            if (!s.enabled) {
                box.innerHTML = '<div class="col-span-full text-sm text-[#F59E0B] bg-[#F59E0B]/10 rounded-xl px-4 py-3">' +
                    '⚠️ Backups are disabled: set <code>ADMIN_CHAT_ID</code> and press Start on @kelembackupbot.</div>';
                return;
            }
            var when = s.exists ? fmtTimeShort(s.created_at) : 'No backup yet';
            var docs = s.exists && s.documents != null ? s.documents : '—';
            var size = s.exists && s.file_size ? (Math.round(s.file_size / 102.4) / 10) + ' KB' : '—';
            box.innerHTML =
                _backupStatCard('Last Backup', when, s.exists ? 'text-[#10B981]' : 'text-gray-500') +
                _backupStatCard('Records Saved', String(docs), 'text-white') +
                _backupStatCard('Snapshot Size', size, 'text-white') +
                _backupStatCard('Live Records', String(s.live_documents != null ? s.live_documents : '—'), 'text-[#3B82F6]');
        })
        .catch(function (e) {
            if (box) box.innerHTML = '<div class="col-span-full text-sm text-red-400 bg-red-500/10 rounded-xl px-4 py-3">Could not load status: ' + escHtml(e.message) + '</div>';
        });
}

function runBackupNow() {
    var btn = document.getElementById('backupNowBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Backing up…'; }
    api('POST', '/api/admin/backup/create')
        .then(function (r) {
            showToast('✅ Backup created — ' + (r.documents || 0) + ' records saved.');
            loadBackupStatus();
        })
        .catch(function (e) {
            showToast('❌ Backup failed: ' + e.message);
        })
        .finally(function () {
            if (btn) { btn.disabled = false; btn.textContent = 'Create Backup'; }
        });
}

function runRestore() {
    var overwrite = !!document.getElementById('backupOverwrite').checked;
    var msg = overwrite
        ? 'Overwrite restore will REPLACE current records with the backup version. Continue?'
        : 'Restore missing records from the latest backup?';
    if (!confirm(msg)) return;

    var btn = document.getElementById('restoreBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Restoring…'; }
    api('POST', '/api/admin/backup/restore', { overwrite: overwrite, confirm: overwrite })
        .then(function (r) {
            var parts = [];
            if (r.inserted) parts.push(r.inserted + ' added');
            if (r.overwritten) parts.push(r.overwritten + ' replaced');
            if (r.skipped) parts.push(r.skipped + ' kept');
            showToast('✅ Restore complete' + (parts.length ? ' — ' + parts.join(', ') : '') + '.');
            loadBackupStatus();
        })
        .catch(function (e) {
            showToast('❌ Restore failed: ' + e.message);
        })
        .finally(function () {
            if (btn) { btn.disabled = false; btn.textContent = 'Restore From Backup'; }
        });
}

function runRestoreFromFile() {
    var fileInput = document.getElementById('backupFile');
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) {
        showToast('❌ Choose a backup JSON file first.');
        return;
    }
    var overwrite = !!document.getElementById('backupUploadOverwrite').checked;
    var msg = overwrite
        ? 'Uploaded restore will REPLACE current records with the file contents. Continue?'
        : 'Uploaded restore will only ADD missing records from the file. Continue?';
    if (!confirm(msg)) return;

    var btn = document.getElementById('restoreFileBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Uploading…'; }

    function _done() {
        if (btn) { btn.disabled = false; btn.textContent = 'Upload & Restore'; }
        if (fileInput) fileInput.value = '';
    }

    var reader = new FileReader();
    reader.onload = function (e) {
        var snapshot;
        try {
            snapshot = JSON.parse(e.target.result);
        } catch (err) {
            showToast('❌ Not a valid JSON file: ' + err.message);
            _done();
            return;
        }
        api('POST', '/api/admin/backup/upload', { snapshot: snapshot, overwrite: overwrite, confirm: overwrite })
            .then(function (r) {
                var parts = [];
                if (r.inserted) parts.push(r.inserted + ' added');
                if (r.overwritten) parts.push(r.overwritten + ' replaced');
                if (r.skipped) parts.push(r.skipped + ' kept');
                showToast('✅ Restored from file' + (parts.length ? ' — ' + parts.join(', ') : '') + '.');
                loadBackupStatus();
            })
            .catch(function (err) {
                showToast('❌ Upload restore failed: ' + err.message);
            })
            .finally(_done);
    };
    reader.onerror = function () {
        showToast('❌ Could not read the file.');
        _done();
    };
    reader.readAsText(file);
}
