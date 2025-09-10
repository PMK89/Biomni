(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  const usersTBody = $('#users-table tbody');
  const runsTBody = $('#runs-table tbody');
  const userSearch = $('#user-search');
  const userCount = $('#user-count');
  const runsHeader = $('#runs-header');
  const logoutBtn = $('#logout-btn');
  const feedbackView = $('#feedback-view');
  const solutionView = $('#solution-view');
  const thinkingView = $('#thinking-view');
  const dlJson = $('#dl-bundle-json');
  const dlTxt = $('#dl-bundle-txt');
  const tabThoughts = $('#tab-thoughts');
  const tabFeedback = $('#tab-feedback');

  let allUsers = [];
  let selectedUser = null;
  let selectedRun = null;

  async function fetchMe() {
    try {
      const res = await fetch('/api/me');
      if (!res.ok) throw new Error('failed /api/me');
      const me = await res.json();
      if (logoutBtn) logoutBtn.href = me.logout_url || '/logout';
      if (!me.is_admin) {
        // Not an admin; bounce back to app
        window.location.href = '/app';
      }
    } catch (e) {
      console.error(e);
      window.location.href = '/app';
    }
  }

  function renderUsers(list) {
    usersTBody.innerHTML = '';
    list.forEach(u => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><span class="badge">${u.user_id}</span></td>
        <td>${u.run_count}</td>
        <td class="muted">${u.last_ts || ''}</td>
      `;
      tr.onclick = () => {
        selectedUser = u.user_id;
        runsHeader.textContent = `for ${selectedUser}`;
        loadRuns(selectedUser);
      };
      usersTBody.appendChild(tr);
    });
    userCount.textContent = `${list.length} users`;
  }

  async function loadUsers() {
    const res = await fetch('/api/admin/users');
    if (res.status === 403) { window.location.href = '/app'; return; }
    const data = await res.json();
    allUsers = data.items || [];
    renderUsers(allUsers);
  }

  userSearch.addEventListener('input', () => {
    const q = (userSearch.value || '').toLowerCase().trim();
    if (!q) return renderUsers(allUsers);
    renderUsers(allUsers.filter(u => (u.user_id || '').toLowerCase().includes(q)));
  });

  function preview(text, max=160) {
    text = text || '';
    return text.length > max ? text.slice(0, max) + '…' : text;
  }

  async function loadRuns(uid) {
    runsTBody.innerHTML = '';
    const res = await fetch(`/api/admin/runs?user_id=${encodeURIComponent(uid)}&limit=200`);
    if (!res.ok) return;
    const data = await res.json();
    const items = data.items || [];
    items.forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="muted">${r.ts || ''}</td>
        <td>${r.model || ''}</td>
        <td>${preview(r.prompt)}</td>
      `;
      tr.onclick = () => { selectRun(uid, r.run_id); };
      runsTBody.appendChild(tr);
    });
  }

  async function selectRun(uid, runId) {
    selectedRun = runId;
    feedbackView.value = '';
    if (solutionView) solutionView.value = '';
    if (thinkingView) thinkingView.value = '';
    try {
      // Load feedback (list)
      const res = await fetch(`/api/admin/feedback?user_id=${encodeURIComponent(uid)}&run_id=${encodeURIComponent(runId)}`);
      if (res.ok) {
        const data = await res.json();
        const lines = (data.items || []).map(f => `[${f.ts}] ${f.username || f.user_id}\n${f.text}\n`);
        feedbackView.value = lines.join('\n');
      }
      // Load run bundle to get solution and thinking
      const rb = await fetch(`/api/admin/run_bundle?user_id=${encodeURIComponent(uid)}&run_id=${encodeURIComponent(runId)}&format=json`);
      if (rb.ok) {
        const bundle = await rb.json();
        const run = bundle.run || {};
        if (solutionView) solutionView.value = run.solution || '';
        if (thinkingView) thinkingView.value = run.thinking || '';
      }
    } catch(e) { console.error(e); }
  }

  // Tabs: Thoughts vs Feedback
  function showTab(which) {
    if (!thinkingView || !feedbackView) return;
    const isThoughts = which === 'thoughts';
    thinkingView.style.display = isThoughts ? '' : 'none';
    feedbackView.style.display = isThoughts ? 'none' : '';
    if (tabThoughts && tabFeedback) {
      if (isThoughts) {
        tabThoughts.classList.add('primary');
        tabThoughts.classList.remove('ghost');
        tabFeedback.classList.add('ghost');
        tabFeedback.classList.remove('primary');
      } else {
        tabFeedback.classList.add('primary');
        tabFeedback.classList.remove('ghost');
        tabThoughts.classList.add('ghost');
        tabThoughts.classList.remove('primary');
      }
    }
  }

  tabThoughts?.addEventListener('click', (e) => { e.preventDefault(); showTab('thoughts'); });
  tabFeedback?.addEventListener('click', (e) => { e.preventDefault(); showTab('feedback'); });

  dlJson.addEventListener('click', () => {
    if (!selectedUser || !selectedRun) return;
    window.open(`/api/admin/run_bundle?user_id=${encodeURIComponent(selectedUser)}&run_id=${encodeURIComponent(selectedRun)}&format=json`, '_blank');
  });
  dlTxt.addEventListener('click', () => {
    if (!selectedUser || !selectedRun) return;
    window.open(`/api/admin/run_bundle?user_id=${encodeURIComponent(selectedUser)}&run_id=${encodeURIComponent(selectedRun)}&format=txt`, '_blank');
  });

  // Init
  fetchMe().then(loadUsers);
  showTab('thoughts');
})();
