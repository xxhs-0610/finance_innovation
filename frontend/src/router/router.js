/**
 * Frontend Router & Navigation Controller with RBAC Guard
 */

export class AppRouter {
  constructor(app) {
    this.app = app;
    this.currentView = 'chat';
    this.viewTitles = {
      chat: { title: '对话窗', desc: '可信问答主交互视窗，支持制度条款定位、报表取数与双向证据追溯' },
      import: { title: '导入台', desc: '多格式原始文件统一导入、解析队列管理与入库流水线' },
      kb: { title: '知识库管理', desc: '监管制度与统计报表文档库、切片索引检索与增量维护' },
      evidence: { title: '证据审查', desc: '单列展示命中文档依据、原文定位信息与动态原文高亮预览' },
      pipeline: { title: '模块对接', desc: '端到端 RAG 架构全流程数据流、模块接口契约与评测监控' }
    };
  }

  init() {
    this.bindEvents();
    this.handleHashChange();
    window.addEventListener('hashchange', () => this.handleHashChange());
  }

  bindEvents() {
    const navMenu = document.getElementById('mainNavMenu');
    if (!navMenu) return;

    navMenu.addEventListener('click', (e) => {
      const item = e.target.closest('.nav-item');
      if (!item) return;

      const targetView = item.dataset.view;
      const isAdminOnly = item.hasAttribute('data-admin-only');
      const currentRole = window.appState ? window.appState.get('role') : 'admin';

      if (isAdminOnly && currentRole !== 'admin') {
        if (window.ToastComponent) {
          window.ToastComponent.show('⚠️ 权限受限：该模块需管理员权限，请在顶部切换为【管理员】', 'warning');
        }
        return;
      }

      this.navigate(targetView);
    });
  }

  handleHashChange() {
    const hash = window.location.hash.replace('#/', '').replace('#', '').trim();
    if (hash && this.viewTitles[hash]) {
      this.switchView(hash);
    } else {
      this.switchView('chat');
    }
  }

  navigate(viewName) {
    if (this.viewTitles[viewName]) {
      window.location.hash = `#/${viewName}`;
    }
  }

  switchView(viewName) {
    this.currentView = viewName;
    if (window.appState) {
      window.appState.setView(viewName);
    }

    // 1. Update Left Nav Active
    document.querySelectorAll('.nav-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.view === viewName);
    });

    // 2. Update Center Panels
    document.querySelectorAll('.view-panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `view-${viewName}`);
    });

    // 3. Update Center Title & Subtitle
    const info = this.viewTitles[viewName] || this.viewTitles.chat;
    const titleEl = document.getElementById('currentViewTitle');
    const descEl = document.getElementById('currentViewDesc');
    if (titleEl) titleEl.textContent = info.title;
    if (descEl) descEl.textContent = info.desc;

    // 4. Update Right Sidebar View Panels
    document.querySelectorAll('.right-view-panel').forEach((panel) => {
      panel.classList.toggle('hidden', panel.dataset.forView !== viewName);
    });

    // Re-render specific controllers if attached
    if (this.app) {
      if (viewName === 'chat' && this.app.chatCtrl) this.app.chatCtrl.render();
      else if (viewName === 'evidence' && this.app.evidenceCtrl) this.app.evidenceCtrl.render();
      else if (viewName === 'import' && this.app.importCtrl) this.app.importCtrl.render();
      else if (viewName === 'kb' && this.app.kbCtrl) this.app.kbCtrl.render();
    }
  }
}

if (typeof window !== 'undefined') {
  window.AppRouter = AppRouter;
}
