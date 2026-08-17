/**
 * RegTrust-RAG Main Application Bootstrap & Router
 * Manages view switching, role permissions guard, session list rendering, toasts, and modals
 */

class App {
  constructor() {
    this.currentView = 'chat';
    this.initControllers();
    this.initRoleSwitcher();
    this.initNavigation();
    this.initSessionList();
    this.initModalContainer();

    // Default view
    this.switchView('chat');
  }

  initControllers() {
    this.chatCtrl = new window.ChatController();
    this.importCtrl = new window.ImportController();
    this.evidenceCtrl = new window.EvidenceController();
    this.kbCtrl = new window.KBController();
    this.pipelineCtrl = new window.PipelineController();
  }

  initRoleSwitcher() {
    const adminBtn = document.getElementById('roleBtnAdmin');
    const userBtn = document.getElementById('roleBtnUser');

    if (adminBtn && userBtn) {
      adminBtn.addEventListener('click', () => {
        window.appState.setRole('admin');
        adminBtn.classList.add('active');
        userBtn.classList.remove('active');
        this.updateRoleUI('admin');
        this.showToast('已切换为【管理员】身份：开放全量导入、知识库治理与链路监控权限', 'success');
      });

      userBtn.addEventListener('click', () => {
        window.appState.setRole('user');
        userBtn.classList.add('active');
        adminBtn.classList.remove('active');
        this.updateRoleUI('user');
        this.showToast('已切换为【普通用户】身份：仅具备合规问答与证据查阅权限', 'info');
        if (this.currentView === 'import' || this.currentView === 'kb') {
          this.switchView('chat');
        }
      });
    }
  }

  updateRoleUI(role) {
    const lockedItems = document.querySelectorAll('[data-admin-only]');
    lockedItems.forEach(el => {
      if (role === 'user') {
        el.classList.add('locked');
        const lockIcon = el.querySelector('.lock-icon');
        if (lockIcon) lockIcon.classList.remove('hidden');
      } else {
        el.classList.remove('locked');
        const lockIcon = el.querySelector('.lock-icon');
        if (lockIcon) lockIcon.classList.add('hidden');
      }
    });
  }

  initNavigation() {
    const navMenu = document.getElementById('mainNavMenu');
    if (!navMenu) return;

    navMenu.addEventListener('click', (e) => {
      const item = e.target.closest('.nav-item');
      if (!item) return;

      const targetView = item.dataset.view;
      const isAdminOnly = item.hasAttribute('data-admin-only');

      if (isAdminOnly && window.appState.get('role') !== 'admin') {
        this.showToast('⚠️ 权限受限：该模块需管理员权限，请在顶部切换为【管理员】', 'warning');
        return;
      }

      this.switchView(targetView);
    });
  }

  switchView(viewName) {
    this.currentView = viewName;
    window.appState.setView(viewName);

    // 1. Update Left Nav Active
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.view === viewName);
    });

    // 2. Update Center Panels
    document.querySelectorAll('.view-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `view-${viewName}`);
    });

    // 3. Update Center Title & Subtitle
    const viewTitles = {
      chat: { title: '对话窗', desc: '可信问答主交互视窗，支持制度条款定位、报表取数与双向证据追溯' },
      import: { title: '导入台', desc: '多格式原始文件统一导入、解析队列管理与入库流水线' },
      kb: { title: '知识库管理', desc: '监管制度与统计报表文档库、切片索引检索与增量维护' },
      evidence: { title: '证据审查', desc: '单列展示命中文档依据、原文定位信息与动态原文高亮预览' },
      pipeline: { title: '模块对接', desc: '端到端 RAG 架构全流程数据流、模块接口契约与评测监控' }
    };

    const info = viewTitles[viewName] || viewTitles.chat;
    const titleEl = document.getElementById('currentViewTitle');
    const descEl = document.getElementById('currentViewDesc');
    if (titleEl) titleEl.textContent = info.title;
    if (descEl) descEl.textContent = info.desc;

    // 4. Update Right Sidebar View Panels
    document.querySelectorAll('.right-view-panel').forEach(panel => {
      panel.classList.toggle('hidden', panel.dataset.forView !== viewName);
    });

    // Re-render specific controllers if needed
    if (viewName === 'chat') this.chatCtrl.render();
    else if (viewName === 'evidence') this.evidenceCtrl.render();
    else if (viewName === 'import') this.importCtrl.render();
    else if (viewName === 'kb') this.kbCtrl.render();
  }

  initSessionList() {
    const listEl = document.getElementById('sessionList');
    const countEl = document.getElementById('sessionCountBadge');
    const newBtn = document.getElementById('sidebarNewChatBtn');

    const renderList = () => {
      const sessions = window.appState.get('sessions') || [];
      const activeId = window.appState.get('activeSessionId');
      if (countEl) countEl.textContent = `${sessions.length}`;

      if (!listEl) return;
      listEl.innerHTML = sessions.map(s => `
        <div class="session-card ${s.id === activeId ? 'active' : ''}" data-session-id="${s.id}">
          <div class="session-title truncate" title="${s.title}">${s.title}</div>
          <div class="session-meta">
            <span class="truncate" style="max-width:120px;">${s.topic}</span>
            <span>${s.updated}</span>
          </div>
        </div>
      `).join('');
    };

    if (listEl) {
      listEl.addEventListener('click', (e) => {
        const card = e.target.closest('.session-card');
        if (!card) return;
        const sId = card.dataset.sessionId;
        window.appState.setActiveSession(sId);
        this.switchView('chat');
      });
    }

    if (newBtn) {
      newBtn.addEventListener('click', () => {
        window.appState.createSession();
        this.switchView('chat');
        const input = document.getElementById('chatInput');
        if (input) input.focus();
        this.showToast('已新建对话窗口', 'success');
      });
    }

    window.appState.subscribe('sessionListUpdated', renderList);
    window.appState.subscribe('sessionChanged', renderList);
    renderList();
  }

  // Toast Notification System
  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const iconMap = {
      success: '✓',
      warning: '⚠️',
      danger: '✕',
      info: 'ℹ️'
    };
    toast.innerHTML = `
      <span style="font-weight:bold;">${iconMap[type] || 'ℹ️'}</span>
      <span>${message}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 2800);
  }

  // Modal Dialog System
  initModalContainer() {
    let backdrop = document.getElementById('modal-backdrop');
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.id = 'modal-backdrop';
      backdrop.className = 'modal-backdrop hidden';
      backdrop.innerHTML = `
        <div class="modal-content">
          <div class="modal-header">
            <div class="modal-title" id="modalTitle">详情预览</div>
            <button class="btn btn-sm btn-ghost" id="modalCloseBtn">✕</button>
          </div>
          <div class="modal-body" id="modalBody"></div>
          <div class="modal-footer">
            <button class="btn btn-primary btn-sm" id="modalConfirmBtn">关闭</button>
          </div>
        </div>
      `;
      document.body.appendChild(backdrop);

      const close = () => backdrop.classList.add('hidden');
      document.getElementById('modalCloseBtn')?.addEventListener('click', close);
      document.getElementById('modalConfirmBtn')?.addEventListener('click', close);
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) close();
      });
    }
  }

  showModal({ title, content }) {
    const backdrop = document.getElementById('modal-backdrop');
    const titleEl = document.getElementById('modalTitle');
    const bodyEl = document.getElementById('modalBody');

    if (backdrop && titleEl && bodyEl) {
      titleEl.innerHTML = title;
      bodyEl.innerHTML = content;
      backdrop.classList.remove('hidden');
    }
  }
}

// Bootstrap on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new App();
});
