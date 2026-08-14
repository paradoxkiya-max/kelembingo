// ==================== RULES ====================
async function showRules() {
    if (!document.querySelector('#rules-modal > *') && window.PageLoader) {
        await PageLoader.loadComponent('rules-modal', 'rules-modal.html');
    }
    var modal = document.getElementById('rules-modal');
    if (modal) modal.classList.remove('hidden');
}
function hideRules() { document.getElementById('rules-modal').classList.add('hidden'); }

function logout() {
    if (tg) tg.close();
    else window.location.reload();
}
