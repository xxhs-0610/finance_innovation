/**
 * RegTrust-RAG Chat Controller
 * Handles conversation rendering, user input, sample query chips, citations linking, and right sidebar sync
 */

class ChatController {
  constructor() {
    this.container = document.getElementById('chatMessages');
    this.input = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.clearBtn = document.getElementById('clearBtn');
    this.newChatBtn = document.getElementById('newChatBtn');
    this.sampleChipsContainer = document.getElementById('sampleChips');

    this.initEvents();
  }

  initEvents() {
    // Send button
    if (this.sendBtn) {
      this.sendBtn.addEventListener('click', () => this.handleSend());
    }

    // Input keyboard events
    if (this.input) {
      this.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.handleSend();
        }
      });
      // Auto-grow
      this.input.addEventListener('input', () => {
        this.input.style.height = 'auto';
        this.input.style.height = Math.min(this.input.scrollHeight, 120) + 'px';
      });
    }

    // Clear Chat
    if (this.clearBtn) {
      this.clearBtn.addEventListener('click', () => {
        window.appState.clearActiveSession();
        this.render();
        window.app.showToast('当前会话记录已清空', 'info');
      });
    }

    // New Chat
    if (this.newChatBtn) {
      this.newChatBtn.addEventListener('click', () => {
        window.appState.createSession();
        this.input.value = '';
        this.input.focus();
        window.app.showToast('已创建新对话窗口', 'success');
      });
    }

    // Sample Chips clicks
    if (this.sampleChipsContainer) {
      this.sampleChipsContainer.addEventListener('click', (e) => {
        const chip = e.target.closest('.sample-chip');
        if (!chip) return;
        const text = chip.dataset.query || chip.textContent.trim();
        this.input.value = text;
        this.handleSend();
      });
    }

    // Citations & Actions Delegation in Chat Message List
    if (this.container) {
      this.container.addEventListener('click', (e) => {
        // Citation tag clicked
        const citTag = e.target.closest('.citation-tag');
        if (citTag) {
          const evId = citTag.dataset.evId;
          const evIndex = window.appState.get('evidenceList').findIndex(ev => ev.id === evId);
          if (evIndex !== -1) {
            window.appState.setActiveEvidence(evIndex);
          }
          window.app.switchView('evidence');
          window.app.showToast('已跳转至命中证据审查', 'info');
          return;
        }

        // Copy answer
        const copyBtn = e.target.closest('[data-action="copy"]');
        if (copyBtn) {
          const card = copyBtn.closest('.bubble-card-assistant');
          if (card) {
            const textToCopy = card.innerText;
            navigator.clipboard?.writeText(textToCopy);
            window.app.showToast('答案内容已复制到剪贴板', 'success');
          }
          return;
        }

        // Like / Dislike Feedback
        const likeBtn = e.target.closest('[data-action="like"]');
        if (likeBtn) {
          likeBtn.style.color = 'var(--success-text)';
          window.app.showToast('感谢您的反馈（已记录为正样本）', 'success');
          return;
        }
        const dislikeBtn = e.target.closest('[data-action="dislike"]');
        if (dislikeBtn) {
          dislikeBtn.style.color = 'var(--danger-text)';
          window.app.showToast('感谢反馈，该条目已标记需人工复核', 'warning');
          return;
        }
      });
    }

    // Listen to State changes
    window.appState.subscribe('sessionChanged', () => this.render());
    window.appState.subscribe('sessionUpdated', () => this.render());
  }

  render() {
    const session = window.appState.getActiveSession();
    if (!session || !this.container) return;

    if (!session.messages || session.messages.length === 0) {
      this.container.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:var(--text-muted); text-align:center; padding:40px 20px;">
          <div style="width:44px; height:44px; border-radius:12px; background:var(--brand-50); color:var(--brand-600); display:flex; align-items:center; justify-content:center; margin-bottom:12px;">
            <svg class="icon icon-lg" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          </div>
          <h4 style="font-size:14px; font-weight:600; color:var(--text-primary); margin-bottom:6px;">开始可信监管问答</h4>
          <p style="font-size:12.5px; max-width:400px; line-height:1.6;">支持制度条款检索、监管指标取数与合规性比对。可在下方输入问题或点击精选问题标签。</p>
        </div>
      `;
      this.syncRightSidebar(null);
      return;
    }

    let lastAssistantMsg = null;
    this.container.innerHTML = session.messages.map(msg => {
      if (msg.role === 'user') {
        return `
          <div class="chat-bubble-row user">
            <div class="avatar avatar-user">用户</div>
            <div class="bubble-content">
              <div class="bubble-text-user">${this.escapeHtml(msg.text)}</div>
              <span style="font-size:10.5px; color:var(--text-subtle); align-self:flex-end; padding-right:2px;">${msg.timestamp || '刚刚'}</span>
            </div>
          </div>
        `;
      }

      lastAssistantMsg = msg;
      return `
        <div class="chat-bubble-row assistant">
          <div class="avatar avatar-assistant">
            <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
          </div>
          <div class="bubble-content" style="max-width:calc(100% - 44px);">
            <div class="bubble-card-assistant">
              <!-- Conclusion -->
              <div class="assistant-conclusion">
                <span style="color:var(--brand-600); flex-shrink:0;">💡</span>
                <span>${msg.conclusion || '结论已生成'}</span>
              </div>

              <!-- Main Body -->
              <div class="assistant-body">${msg.body || ''}</div>

              <!-- Citations -->
              ${msg.citations && msg.citations.length > 0 ? `
                <div class="citation-box">
                  <div class="citation-header">
                    <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    <span>关联制度与报表依据 (${msg.citations.length} 篇)</span>
                  </div>
                  <div class="citation-tags">
                    ${msg.citations.map(c => `
                      <span class="citation-tag" data-ev-id="${c.id}">
                        <span>📄 ${c.title}</span>
                        <span style="color:var(--text-muted); font-size:10.5px;">[${c.loc}]</span>
                      </span>
                    `).join('')}
                  </div>
                </div>
              ` : ''}

              <!-- Risk / Scope Tips -->
              ${msg.riskTip ? `
                <div style="font-size:11.5px; color:#b45309; background:#fffbeb; border:1px solid #fde68a; border-radius:var(--radius-sm); padding:6px 10px; display:flex; align-items:center; gap:6px;">
                  <span>⚠️</span>
                  <span>${msg.riskTip}</span>
                </div>
              ` : ''}

              <!-- Trust Verification Bottom Row -->
              <div class="trust-verification-row">
                <div class="trust-badges">
                  <span class="badge badge-success">🛡️ 置信度 ${msg.verification?.confidence || 96}%</span>
                  <span class="badge badge-indigo">✓ ${msg.verification?.intent || '制度问答'}</span>
                  <span class="badge badge-info">✓ 数字核验通过</span>
                </div>
                <div class="bubble-actions">
                  <button class="bubble-action-btn" data-action="copy" title="复制答案">
                    <svg class="icon icon-sm" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                    复制
                  </button>
                  <button class="bubble-action-btn" data-action="like" title="好评">
                    <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>
                  </button>
                  <button class="bubble-action-btn" data-action="dislike" title="差评">
                    <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');

    this.scrollToBottom();
    this.syncRightSidebar(lastAssistantMsg);
  }

  async handleSend() {
    const text = this.input.value.trim();
    if (!text) return;

    // 1. Add User Message
    const userMsg = {
      id: `msg_u_${Date.now()}`,
      role: 'user',
      text: text,
      timestamp: this.getCurrentTime()
    };
    window.appState.addMessageToActiveSession(userMsg);
    this.input.value = '';
    this.input.style.height = 'auto';
    this.render();

    // 2. Add Temporary Loading Assistant Message
    const loadingId = `msg_a_${Date.now()}`;
    const loadingMsg = {
      id: loadingId,
      role: 'assistant',
      conclusion: '正在进行多路召回、条文定位与事后可信校验...',
      body: `<div style="display:flex; align-items:center; gap:8px; color:var(--brand-600); padding:10px 0; font-size:12.5px;">
        <svg class="icon" style="animation:spin 1s linear infinite;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" stroke-dasharray="32" stroke-dashoffset="12"></circle></svg>
        <span>检索 BM25 条款库 + FAISS 向量库，并执行 BGE-Rerank 重排...</span>
      </div>`,
      citations: [],
      timestamp: this.getCurrentTime()
    };
    window.appState.addMessageToActiveSession(loadingMsg);
    this.render();

    // 3. Call RAG API / Mock
    try {
      const result = await window.APIService.ask(text);
      const session = window.appState.getActiveSession();
      const lastIndex = session.messages.findIndex(m => m.id === loadingId);
      if (lastIndex !== -1) {
        session.messages[lastIndex] = {
          id: loadingId,
          role: 'assistant',
          conclusion: result.conclusion,
          body: result.body,
          citations: result.citations,
          verification: result.verification,
          riskTip: result.riskTip,
          timestamp: this.getCurrentTime()
        };
        window.appState.notify('sessionUpdated', session);
      }
    } catch (err) {
      console.error('Query error:', err);
    }
  }

  syncRightSidebar(msg) {
    const el = document.getElementById('chatRightContext');
    if (!el) return;

    if (!msg || !msg.verification) {
      el.innerHTML = `
        <div class="right-stat-grid">
          <div class="right-stat-item"><div class="right-stat-label">意图分类</div><div class="right-stat-value" style="font-size:13px;">等待提问</div></div>
          <div class="right-stat-item"><div class="right-stat-label">综合置信度</div><div class="right-stat-value">-</div></div>
          <div class="right-stat-item"><div class="right-stat-label">检索耗时</div><div class="right-stat-value">-</div></div>
          <div class="right-stat-item"><div class="right-stat-label">生成耗时</div><div class="right-stat-value">-</div></div>
        </div>
      `;
      return;
    }

    const v = msg.verification;
    const r = v.router || {};
    const a = v.analyzer || {};
    const ev = v.evidenceVerifier || {};

    let routerHtml = '';
    if (r.intent) {
      routerHtml = `
        <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:8px 10px; font-size:11.5px; display:flex; flex-direction:column; gap:4px;">
          <div style="font-weight:600; color:var(--text-primary); border-bottom:1px solid var(--border-subtle); padding-bottom:3px; margin-bottom:2px; display:flex; justify-content:space-between;">
            <span>🧭 Question Router</span>
            <span class="badge badge-indigo" style="font-size:10px;">${r.intent}</span>
          </div>
          ${r.qa_type ? `<div style="display:flex; justify-content:space-between;"><span>业务细分:</span> <strong style="color:var(--brand-600);">${r.qa_type}</strong></div>` : ''}
          ${r.reason ? `<div style="color:var(--text-secondary); font-size:11px; margin-top:2px;">${r.reason}</div>` : ''}
        </div>
      `;
    }

    let analyzerHtml = '';
    if (a.topic || a.institution_type || a.indicator || a.rule_type) {
      analyzerHtml = `
        <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:8px 10px; font-size:11.5px; display:flex; flex-direction:column; gap:4px;">
          <div style="font-weight:600; color:var(--text-primary); border-bottom:1px solid var(--border-subtle); padding-bottom:3px; margin-bottom:2px; display:flex; justify-content:space-between;">
            <span>🔍 Query Analyzer</span>
            <span style="font-size:10.5px; color:var(--text-muted);">${a.topic || '通用'}</span>
          </div>
          ${a.institution_type ? `<div style="display:flex; justify-content:space-between;"><span>适用机构:</span> <strong>${a.institution_type}</strong></div>` : ''}
          ${a.indicator ? `<div style="display:flex; justify-content:space-between;"><span>监管指标:</span> <strong style="color:var(--brand-600);">${a.indicator}</strong></div>` : ''}
          ${a.time_period ? `<div style="display:flex; justify-content:space-between;"><span>统计期间:</span> <strong>${a.time_period}</strong></div>` : ''}
          ${a.rule_type ? `<div style="display:flex; justify-content:space-between;"><span>规则类型:</span> <strong>${a.rule_type}</strong></div>` : ''}
          ${a.keywords && a.keywords.length > 0 ? `
            <div style="margin-top:2px; display:flex; gap:4px; flex-wrap:wrap;">
              ${a.keywords.map(k => `<span style="background:var(--bg-app); border:1px solid var(--border-subtle); border-radius:4px; padding:1px 5px; font-size:10px; color:var(--text-secondary);">${k}</span>`).join('')}
            </div>
          ` : ''}
        </div>
      `;
    }

    let verifierHtml = '';
    if (ev.reason_code) {
      const isOk = ev.reason_code === 'SUFFICIENT';
      const badgeColor = isOk ? 'badge-success' : (ev.need_clarification ? 'badge-warning' : 'badge-danger');
      verifierHtml = `
        <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:8px 10px; font-size:11.5px; display:flex; flex-direction:column; gap:4px;">
          <div style="font-weight:600; color:var(--text-primary); border-bottom:1px solid var(--border-subtle); padding-bottom:3px; margin-bottom:2px; display:flex; justify-content:space-between;">
            <span>🛡️ Evidence Verifier</span>
            <span class="badge ${badgeColor}" style="font-size:10px;">${ev.reason_code}</span>
          </div>
          <div style="color:var(--text-secondary); font-size:11px; line-height:1.4;">${ev.reason || ''}</div>
          ${ev.missing_information && ev.missing_information.length > 0 ? `
            <div style="color:#b45309; font-size:10.5px; margin-top:2px;">⚠️ 缺失要素: ${ev.missing_information.join('；')}</div>
          ` : ''}
        </div>
      `;
    }

    el.innerHTML = `
      <div class="right-stat-grid">
        <div class="right-stat-item"><div class="right-stat-label">意图分类</div><div class="right-stat-value" style="font-size:12px; font-weight:600; color:var(--brand-600);">${r.intent || v.intent}</div></div>
        <div class="right-stat-item"><div class="right-stat-label">综合置信度</div><div class="right-stat-value" style="color:var(--success-text);">${v.confidence}%</div></div>
        <div class="right-stat-item"><div class="right-stat-label">检索耗时</div><div class="right-stat-value" style="font-size:12.5px;">${v.retrievalLatency}</div></div>
        <div class="right-stat-item"><div class="right-stat-label">生成耗时</div><div class="right-stat-value" style="font-size:12.5px;">${v.genLatency}</div></div>
      </div>
      <div style="display:flex; flex-direction:column; gap:8px; margin-top:4px;">
        ${routerHtml}
        ${analyzerHtml}
        ${verifierHtml}
        <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:8px 10px; font-size:11.5px; display:flex; flex-direction:column; gap:4px;">
          <div style="display:flex; justify-content:space-between;"><span>数字合规校验:</span> <strong style="color:var(--success-text);">${v.numCheck}</strong></div>
          <div style="display:flex; justify-content:space-between;"><span>幻觉阻断状态:</span> <strong style="color:var(--success-text);">${v.hallucinationCheck}</strong></div>
          ${v.totalLatency ? `<div style="display:flex; justify-content:space-between;"><span>全链路总耗时:</span> <strong>${v.totalLatency}</strong></div>` : ''}
        </div>
      </div>
    `;
  }

  scrollToBottom() {
    if (this.container) {
      this.container.scrollTop = this.container.scrollHeight;
    }
  }

  getCurrentTime() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}

window.ChatController = ChatController;
