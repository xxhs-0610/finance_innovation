/**
 * RegTrust-RAG Frontend Application Bootstrap
 * Standardized modular architecture entry point
 */

import { AppRouter } from './router/router.js';
import { ToastComponent } from './components/toast.js';
import { ModalComponent } from './components/modal.js';
import { APIService } from './api/api_service.js';

export class App {
  constructor() {
    this.initControllers();
    this.initRoleSwitcher();
    this.initSessionList();
    ModalComponent.init();

    this.router = new AppRouter(this);
    this.router.init();

    // Check backend health on boot
    APIService.checkBackendHealth().then((isHealthy) => {
      if (isHealthy) {
        console.log('✅ Connected to FastAPI backend server (http://127.0.0.1:8000)');
      } else {
        console.log('⚡ Running in Standalone / Offline Simulation mode with built-in financial domain knowledge');
      }
    });
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
        ToastComponent.show('已切换为【管理员】身份：开放全量导入、知识库治理与链路监控权限', 'success');
      });

      userBtn.addEventListener('click', () => {
        window.appState.setRole('user');
        userBtn.classList.add('active');
        adminBtn.classList.remove('active');
        this.updateRoleUI('user');
        ToastComponent.show('已切换为【普通用户】身份：仅具备合规问答与证据查阅权限', 'info');
        if (this.router.currentView === 'import' || this.router.currentView === 'kb') {
          this.router.navigate('chat');
        }
      });
    }
  }

  updateRoleUI(role) {
    const lockedItems = document.querySelectorAll('[data-admin-only]');
    lockedItems.forEach((el) => {
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

  initSessionList() {
    const listEl = document.getElementById('sessionList');
    const countEl = document.getElementById('sessionCountBadge');
    const newBtn = document.getElementById('sidebarNewChatBtn');

    const renderList = () => {
      const sessions = window.appState.get('sessions') || [];
      const activeId = window.appState.get('activeSessionId');
      if (countEl) countEl.textContent = `${sessions.length}`;

      if (!listEl) return;
      listEl.innerHTML = sessions.map((s) => `
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
        this.router.navigate('chat');
      });
    }

    if (newBtn) {
      newBtn.addEventListener('click', () => {
        window.appState.createSession();
        this.router.navigate('chat');
        const input = document.getElementById('chatInput');
        if (input) input.focus();
        ToastComponent.show('已新建对话窗口', 'success');
      });
    }

    window.appState.subscribe('sessionListUpdated', renderList);
    window.appState.subscribe('sessionChanged', renderList);
    renderList();
  }

  showToast(message, type = 'info') {
    ToastComponent.show(message, type);
  }

  showModal(params) {
    ModalComponent.show(params);
  }
}

// Bootstrap on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new App();
});
