// Biomni Advanced UI Frontend
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  const chatWindow = $('#chat-window');
  const timeline = $('#timeline');
  const chatInput = $('#chat-input');
  const sendBtn = $('#send-btn');
  const fileInput = $('#file-input');
  const userEmail = $('#user-email');
  const logoutBtn = $('#logout-btn');
  const sessionSelect = $('#session-select');
  const refreshSessionsBtn = $('#refresh-sessions');
  const loadSessionBtn = $('#load-session');
  const dlNotebookBtn = $('#dl-notebook');
  const dlLogsBtn = $('#dl-logs');
  const dlFilesBtn = $('#dl-files');
  const dlBundleJsonBtn = $('#dl-bundle-json');
  const dlBundleTxtBtn = $('#dl-bundle-txt');
  const viewFeedbackBtn = $('#view-feedback');
  const myFeedbackView = $('#my-feedback-view');
  const feedbackText = $('#feedback-text');
  const feedbackStatus = $('#feedback-status');
  const submitFeedback = $('#submit-feedback');
  const usageStats = $('#usage-stats');
  const examplesBox = $('#examples');
  const auditToggles = $$('.audit-toggle');

  const state = {
    uploadedPaths: [], // absolute server stored paths
    currentJobId: null,
    thinkingInterval: null,
    sessions: [],
    model: 'GPT-5',
    audit: true,
    loadedRunId: null
  };

  function syncAuditToggles(enabled) {
    auditToggles.forEach(toggle => {
      toggle.checked = enabled;
    });
  }

  async function updatePreferences(modelOverride) {
    const payload = {
      model: modelOverride ?? state.model,
      audit: state.audit
    };
    try {
      await fetch('/api/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (err) {
      console.warn('Failed to update preferences', err);
    }
  }

  // Utilities
  function escapeHtml(s) {
    return (s ?? '').replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  }

  function mdToHtml(md) {
    // Minimal markdown: code fences and links
    let html = escapeHtml(md);
    // code fences
    html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (m, lang, code) => (
      `<pre><code>${escapeHtml(code)}</code></pre>`
    ));
    // inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // links [text](url)
    html = html.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // newlines
    html = html.replace(/\n/g, '<br/>');
    return html;
  }

  function addMessage(role, content, meta = '') {
    $('.empty-state', chatWindow)?.remove();
    const wrapper = document.createElement('div');
    wrapper.className = `message ${role}`;
    wrapper.innerHTML = `
      <div class="avatar">${role === 'user' ? 'U' : 'A'}</div>
      <div class="bubble">
        ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ''}
        <div class="content">${mdToHtml(content || '')}</div>
      </div>
    `;
    chatWindow.appendChild(wrapper);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return wrapper;
  }

  function setAssistantThinking(wrapper) {
    const contentEl = $('.content', wrapper);
    let dots = 0;
    contentEl.textContent = 'Thinking';
    state.thinkingInterval = setInterval(() => {
      dots = (dots + 1) % 4;
      contentEl.textContent = 'Thinking' + '.'.repeat(dots);
    }, 500);
  }

  function clearThinking() {
    if (state.thinkingInterval) {
      clearInterval(state.thinkingInterval);
      state.thinkingInterval = null;
    }
  }

  function renderEvent(evt) {
    const div = document.createElement('div');
    div.className = 'event';
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = evt.title || 'Event';
    div.appendChild(title);

    const content = document.createElement('div');
    content.className = 'content';

    if (evt.type === 'reasoning' && Array.isArray(evt.items)) {
      const ul = document.createElement('ul');
      evt.items.forEach(i => {
        const li = document.createElement('li');
        li.textContent = i;
        ul.appendChild(li);
      });
      content.appendChild(ul);
    } else if (evt.type === 'code' && evt.code) {
      const pre = document.createElement('pre');
      pre.textContent = evt.code;
      content.appendChild(pre);
    } else if (evt.type === 'logs') {
      const pre = document.createElement('pre');
      pre.textContent = evt.text || '';
      content.appendChild(pre);
    } else if (evt.type === 'observation' && Array.isArray(evt.lines)) {
      // Look for image paths and render previews
      const imgPaths = [];
      const textLines = [];
      const imgRe = /(\/[^\s]+\.(png|jpg|jpeg|gif|svg))/i;
      evt.lines.forEach(line => {
        const m = line.match(imgRe);
        if (m) {
          imgPaths.push(m[1]);
        } else {
          textLines.push(line);
        }
      });
      if (textLines.length) {
        const pre = document.createElement('pre');
        pre.textContent = textLines.join('\n');
        content.appendChild(pre);
      }
      imgPaths.forEach(p => {
        const img = document.createElement('img');
        // Serve via authenticated download endpoint
        img.src = `/download?p=${encodeURIComponent(p)}`;
        img.alt = p.split('/').pop();
        img.style.marginTop = '8px';
        content.appendChild(img);
      });
    } else if (evt.type === 'info' && evt.title) {
      // already shown in title
      if (evt.text) {
        content.innerHTML = mdToHtml(evt.text);
      }
    } else {
      content.innerHTML = mdToHtml(evt.text || '');
    }

    if (content.childNodes.length) div.appendChild(content);
    timeline.appendChild(div);
    timeline.scrollTop = timeline.scrollHeight;
  }

  function renderTimeline(job) {
    timeline.innerHTML = '';
    (job.events || []).forEach(renderEvent);
    if (Array.isArray(job.logs) && job.logs.length) {
      renderEvent({ type: 'logs', title: 'Console output', text: job.logs.join('\n') });
    }
    if (job.audit_html) {
      const div = document.createElement('div');
      div.className = 'event';
      const title = document.createElement('div');
      title.className = 'title';
      title.textContent = 'Audit';
      const content = document.createElement('div');
      content.className = 'content';
      content.innerHTML = job.audit_html;
      div.appendChild(title);
      div.appendChild(content);
      timeline.appendChild(div);
    }
  }

  function resetChatPanels() {
    clearThinking();
    chatWindow.innerHTML = '';
    timeline.innerHTML = '';
  }

  function renderRun(run) {
    resetChatPanels();
    state.uploadedPaths = [];
    state.loadedRunId = run.run_id || null;
    state.currentJobId = null;

    if (run.prompt) {
      addMessage('user', run.prompt, 'Prompt');
    }
    if (run.solution) {
      addMessage('assistant', run.solution, 'Solution');
    }
    if (!run.prompt && !run.solution) {
      chatWindow.innerHTML = '<div class="empty-state">No transcript recorded for this session.</div>';
    }

    const thinkingLines = (run.thinking || '').split(/\r?\n/);
    renderTimeline({
      events: [],
      logs: thinkingLines,
      audit_html: run.audit_html
    });
    if (Array.isArray(run.uploads) && run.uploads.length) {
      const filenames = run.uploads.map(u => {
        if (!u) return '';
        try { return u.split('/').pop(); } catch (err) { return u; }
      }).filter(Boolean);
      if (filenames.length) {
        renderEvent({ type: 'info', title: 'Uploaded files', text: filenames.join(', ') });
      }
    }
  }

  async function loadRunDetails(runId) {
    let run = state.sessions.find(r => r.run_id === runId);
    if (run) {
      return run;
    }
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!res.ok) {
      throw new Error('Failed to load session details');
    }
    run = await res.json();
    if (run && !run.uploads && run.uploads_json) {
      try {
        run.uploads = JSON.parse(run.uploads_json);
      } catch (err) {
        run.uploads = [];
      }
    }
    if (run && run.run_id && !state.sessions.find(r => r.run_id === run.run_id)) {
      state.sessions.unshift(run);
    }
    return run;
  }

  function populateExamples() {
    const examples = [
      'Find pathways enriched for the gene set TP53, EGFR, BRCA1.',
      'Summarize recent research on CRISPR off-target effects.',
      'Analyze differential expression from my uploaded RNA-seq counts.',
      'Generate a volcano plot from the CSV I uploaded.'
    ];
    examplesBox.innerHTML = '';
    examples.forEach(q => {
      const div = document.createElement('div');
      div.className = 'example';
      div.textContent = q;
      div.onclick = () => { chatInput.value = q; chatInput.focus(); };
      examplesBox.appendChild(div);
    });
  }

  async function fetchMe() {
    const res = await fetch('/api/me');
    if (!res.ok) return;
    const me = await res.json();
    userEmail.textContent = me.email || me.name || 'User';
    logoutBtn.href = me.logout_url || '/logout';
    // Toggle Admin button
    try {
      const adminBtn = document.getElementById('admin-btn');
      if (adminBtn) adminBtn.style.display = me.is_admin ? 'inline-block' : 'none';
    } catch (e) {}
    // model
    state.model = me.model_preference || state.model;
    state.audit = me.audit_enabled === undefined ? true : !!me.audit_enabled;
    $$('input[name="model"]').forEach(r => {
      r.checked = (r.value === state.model);
    });
    syncAuditToggles(state.audit);
  }

  async function fetchUsage() {
    const res = await fetch('/api/usage');
    if (!res.ok) return;
    const u = await res.json();
    usageStats.innerHTML = `
      <div>Estimated cost (this request): $${u.this_request_estimate?.toFixed?.(4) ?? '0.0000'}</div>
      <div>Weekly cost: $${u.weekly_cost?.toFixed?.(2) ?? '0.00'}</div>
      <div>Total cost: $${u.total_cost?.toFixed?.(2) ?? '0.00'}</div>
      <div>Weekly requests: ${u.weekly_requests}</div>
      <div>Total requests: ${u.total_requests}</div>
    `;
  }

  async function refreshSessions() {
    const current = sessionSelect.value || state.loadedRunId || '';
    const res = await fetch('/api/runs?limit=100');
    if (!res.ok) return;
    const data = await res.json();
    state.sessions = data.items || [];
    sessionSelect.innerHTML = '';
    state.sessions.forEach(r => {
      const opt = document.createElement('option');
      const ts = (r.ts || '').replace('T',' ').split('+')[0].split('Z')[0];
      const prompt = (r.prompt || '').replace(/\n/g, ' ');
      const short = prompt.length > 60 ? prompt.slice(0,57) + '...' : prompt;
      opt.value = r.run_id;
      opt.textContent = `${ts} · ${short} · ${r.run_id.slice(0,8)}`;
      sessionSelect.appendChild(opt);
    });
    if (current) {
      const option = Array.from(sessionSelect.options).find(opt => opt.value === current);
      if (option) {
        sessionSelect.value = current;
      }
    }
  }

  async function uploadFile(file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/upload/file', { method: 'POST', body: form });
    if (!res.ok) throw new Error('Upload failed');
    const out = await res.json();
    if (out.stored_path) state.uploadedPaths.push(out.stored_path);
    return out;
  }

  async function startChat(prompt) {
    const body = { prompt, uploads: state.uploadedPaths, audit: state.audit };
    const res = await fetch('/api/chat/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    if (!res.ok) {
      let msg = 'Failed to start job';
      try {
        const t = await res.text();
        if (t) msg = `${msg}: ${res.status} ${res.statusText} - ${t}`;
      } catch (e) {}
      throw new Error(msg);
    }
    const { job_id } = await res.json();
    state.currentJobId = job_id;
    pollStatus(job_id);
  }

  async function pollStatus(jobId) {
    const res = await fetch(`/api/chat/status/${jobId}`);
    if (!res.ok) return;
    const job = await res.json();
    renderTimeline(job);

    if (job.status === 'running') {
      setTimeout(() => pollStatus(jobId), 1000);
      return;
    }

    // Done or error
    clearThinking();
    if (job.status === 'done') {
      // Replace the last assistant bubble (thinking) with final content
      const lastAssistant = $$('.message.assistant').slice(-1)[0];
      if (lastAssistant) $('.content', lastAssistant).innerHTML = mdToHtml(job.solution || '');
      // Reset uploads for next run
      state.uploadedPaths = [];
      if (job.run_id) {
        const ts = (job.completed || job.created || '').replace('T',' ').split('+')[0].split('Z')[0];
        const prompt = (job.prompt || '').replace(/\n/g, ' ');
        const short = prompt.length > 60 ? prompt.slice(0,57) + '...' : prompt;
        const optionText = `${ts} · ${short} · ${job.run_id.slice(0,8)}`;
        const existing = Array.from(sessionSelect.options).some(opt => opt.value === job.run_id);
        if (!existing) {
          const opt = document.createElement('option');
          opt.value = job.run_id;
          opt.textContent = optionText;
          sessionSelect.prepend(opt);
        }
        sessionSelect.value = job.run_id;
      }
      await fetchMe();
      await fetchUsage();
      await refreshSessions();
      try {
        const run = await loadRunDetails(job.run_id || sessionSelect.value);
        if (run) {
          renderRun(run);
        }
      } catch (err) {
        console.warn('Unable to auto-load completed run', err);
      }
    } else if (job.status === 'error') {
      const lastAssistant = $$('.message.assistant').slice(-1)[0];
      if (lastAssistant) $('.content', lastAssistant).textContent = `Error: ${job.error}`;
    }
  }

  // Event bindings
  sendBtn.addEventListener('click', async () => {
    const text = chatInput.value.trim();
    if (!text) return;

    addMessage('user', text);
    const thinking = addMessage('assistant', 'Thinking...');
    setAssistantThinking(thinking);

    chatInput.value = '';
    try {
      await startChat(text);
    } catch (e) {
      clearThinking();
      $('.content', thinking).textContent = String(e.message || 'Error starting job');
    }
  });

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendBtn.click();
    }
  });

  $('.attach').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const userMsg = `Attached file: ${file.name}`;
    addMessage('user', userMsg, 'Upload');
    try {
      const out = await uploadFile(file);
      addMessage('assistant', `File received: ${out.filename}`, 'Upload');
    } catch (err) {
      addMessage('assistant', `Upload failed`, 'Upload');
    } finally {
      fileInput.value = '';
    }
  });

  refreshSessionsBtn.addEventListener('click', refreshSessions);

  loadSessionBtn?.addEventListener('click', async () => {
    const runId = sessionSelect.value;
    if (!runId) return;
    try {
      const run = await loadRunDetails(runId);
      if (run) {
        renderRun(run);
      }
    } catch (err) {
      console.error('Failed to load session', err);
    }
  });

  dlNotebookBtn.addEventListener('click', () => {
    const rid = sessionSelect.value;
    if (rid) window.open(`/api/export/${encodeURIComponent(rid)}/notebook`, '_blank');
  });
  dlLogsBtn.addEventListener('click', () => {
    const rid = sessionSelect.value;
    if (rid) window.open(`/api/export/${encodeURIComponent(rid)}/logs`, '_blank');
  });
  dlFilesBtn.addEventListener('click', () => {
    const rid = sessionSelect.value;
    if (rid) window.open(`/api/export/${encodeURIComponent(rid)}/files`, '_blank');
  });

  submitFeedback.addEventListener('click', async () => {
    const text = feedbackText.value.trim();
    if (!text) return;
    const run_id = sessionSelect.value || null;
    const res = await fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, run_id }) });
    if (res.ok) {
      feedbackStatus.textContent = 'Thanks for your feedback!';
      feedbackText.value = '';
      setTimeout(() => feedbackStatus.textContent = '', 2000);
    } else {
      feedbackStatus.textContent = 'Failed to submit feedback.';
      setTimeout(() => feedbackStatus.textContent = '', 3000);
    }
  });

  // User bundle downloads
  dlBundleJsonBtn?.addEventListener('click', () => {
    const rid = sessionSelect.value;
    if (!rid) return;
    window.open(`/api/run_bundle?run_id=${encodeURIComponent(rid)}&format=json`, '_blank');
  });
  dlBundleTxtBtn?.addEventListener('click', () => {
    const rid = sessionSelect.value;
    if (!rid) return;
    window.open(`/api/run_bundle?run_id=${encodeURIComponent(rid)}&format=txt`, '_blank');
  });

  // View my feedback for selected run
  viewFeedbackBtn?.addEventListener('click', async () => {
    const rid = sessionSelect.value;
    if (!rid) return;
    try {
      const res = await fetch(`/api/feedback?run_id=${encodeURIComponent(rid)}`);
      if (!res.ok) return;
      const data = await res.json();
      const lines = (data.items || []).map(f => `[${f.ts}] ${f.username || f.user_id}\n${f.text}\n`);
      myFeedbackView.value = lines.join('\n');
    } catch (e) {
      myFeedbackView.value = 'Failed to load feedback.';
    }
  });

  $$('input[name="model"]').forEach(radio => {
    radio.addEventListener('change', async (e) => {
      if (!e.target.checked) return;
      const model = e.target.value;
      state.model = model;
      await updatePreferences(model);
    });
  });

  auditToggles.forEach(toggle => {
    toggle.addEventListener('change', async (e) => {
      state.audit = !!e.target.checked;
      syncAuditToggles(state.audit);
      await updatePreferences();
    });
  });

  // Bootstrap
  populateExamples();
  fetchMe();
  fetchUsage();
  refreshSessions();

  // Ensure only one accordion per column is open in the bottom 2x3 grid
  function setupAccordionExclusivity() {
    const all = Array.from(document.querySelectorAll('.accordions-grid details[data-col]'));
    all.forEach(d => {
      d.addEventListener('toggle', () => {
        if (!d.open) return;
        const col = d.getAttribute('data-col');
        all.forEach(other => {
          if (other !== d && other.getAttribute('data-col') === col) {
            other.open = false;
          }
        });
      });
    });
  }
  setupAccordionExclusivity();
})();
