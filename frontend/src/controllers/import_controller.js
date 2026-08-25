/**
 * RegTrust-RAG Import Workbench Controller
 * Handles 4-category file intake (Word / PDF / Excel / QA), drag-and-drop, queue progress, and parsing simulation
 */

class ImportController {
  constructor() {
    this.fileInput = document.getElementById('filePicker');
    this.dropzone = document.getElementById('dropzone');
    this.queueContainer = document.getElementById('importQueueList');
    this.queueCountEl = document.getElementById('queueCount');
    this.parseAllBtn = document.getElementById('parseAllBtn');
    this.clearQueueBtn = document.getElementById('clearQueueBtn');

    this.initEvents();
  }

  initEvents() {
    // 4 Category Buttons Delegation
    document.querySelectorAll('[data-import-type]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        if (!this.checkPermission()) return;
        const type = btn.dataset.importType;
        if (this.fileInput) {
          if (type === 'word') this.fileInput.accept = '.doc,.docx';
          else if (type === 'pdf') this.fileInput.accept = '.pdf';
          else if (type === 'excel') this.fileInput.accept = '.xls,.xlsx';
          else if (type === 'qa') this.fileInput.accept = '.xlsx,.csv,.jsonl';
          this.fileInput.click();
        }
      });
    });

    // Native File Input change
    if (this.fileInput) {
      this.fileInput.addEventListener('change', (e) => {
        if (!this.checkPermission()) return;
        const files = Array.from(e.target.files);
        if (files.length > 0) {
          this.handleFilesAdded(files);
        }
        this.fileInput.value = '';
      });
    }

    // Drag & Drop
    if (this.dropzone) {
      ['dragenter', 'dragover'].forEach(name => {
        this.dropzone.addEventListener(name, (e) => {
          e.preventDefault();
          this.dropzone.classList.add('dragover');
        });
      });

      ['dragleave', 'drop'].forEach(name => {
        this.dropzone.addEventListener(name, (e) => {
          e.preventDefault();
          this.dropzone.classList.remove('dragover');
        });
      });

      this.dropzone.addEventListener('drop', (e) => {
        if (!this.checkPermission()) return;
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
          this.handleFilesAdded(files);
        }
      });

      this.dropzone.addEventListener('click', () => {
        if (!this.checkPermission()) return;
        if (this.fileInput) {
          this.fileInput.accept = '.doc,.docx,.pdf,.xls,.xlsx,.csv,.jsonl';
          this.fileInput.click();
        }
      });
    }

    // Parse All Button
    if (this.parseAllBtn) {
      this.parseAllBtn.addEventListener('click', () => {
        if (!this.checkPermission()) return;
        this.startBatchParsing();
      });
    }

    // Clear Queue
    if (this.clearQueueBtn) {
      this.clearQueueBtn.addEventListener('click', () => {
        if (!this.checkPermission()) return;
        window.appState.state.importQueue = [];
        window.appState.notify('queueUpdated', []);
        window.app.showToast('导入队列已清空', 'info');
      });
    }

    // State listeners
    window.appState.subscribe('queueUpdated', () => this.render());
    this.render();
  }

  checkPermission() {
    if (window.appState.get('role') !== 'admin') {
      window.app.showToast('⚠️ 权限不足：仅管理员具备文件导入与知识库更新权限', 'warning');
      return false;
    }
    return true;
  }

  handleFilesAdded(files) {
    const queue = window.appState.get('importQueue');
    files.forEach(file => {
      const ext = file.name.split('.').pop().toLowerCase();
      let type = 'word';
      let path = 'data/raw/nfra_page_attachments_500/';
      if (/pdf/i.test(ext)) type = 'pdf';
      else if (/xls|xlsx/i.test(ext)) type = 'excel';
      else if (/qa|csv|jsonl/i.test(file.name) || /csv|jsonl/i.test(ext)) {
        type = 'qa';
        path = 'data/raw/qa/';
      }

      const newItem = {
        id: `q_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
        name: file.name,
        type: type,
        size: `${(file.size / 1024 / 1024).toFixed(2)} MB`,
        path: path,
        status: '待解析',
        progress: 0,
        dot: 'wait'
      };
      queue.unshift(newItem);
    });

    window.appState.notify('queueUpdated', queue);
    window.app.showToast(`已成功添加 ${files.length} 份文件至导入队列`, 'success');
  }

  startBatchParsing() {
    const queue = window.appState.get('importQueue');
    const pending = queue.filter(q => q.status === '待解析' || q.status === '已入队');
    if (pending.length === 0) {
      window.app.showToast('当前队列中所有文件均已完成解析入库', 'info');
      return;
    }

    window.app.showToast(`开始批量解析 ${pending.length} 个文件...`, 'info');
    pending.forEach((item, idx) => {
      item.status = '解析中...';
      item.dot = 'wait';
      let currentProg = 0;
      const timer = setInterval(() => {
        currentProg += 20;
        item.progress = Math.min(currentProg, 100);
        if (currentProg >= 100) {
          clearInterval(timer);
          item.status = '已入库';
          item.dot = 'ok';
          window.appState.notify('queueUpdated', queue);
          if (idx === pending.length - 1) {
            window.app.showToast('全部文件解析与向量索引构建完成！', 'success');
          }
        } else {
          window.appState.notify('queueUpdated', queue);
        }
      }, 250);
    });
  }

  render() {
    const queue = window.appState.get('importQueue') || [];
    if (this.queueCountEl) {
      this.queueCountEl.textContent = `${queue.length} 个文件`;
    }

    if (!this.queueContainer) return;

    if (queue.length === 0) {
      this.queueContainer.innerHTML = `
        <div style="text-align:center; padding:24px 10px; color:var(--text-muted); font-size:12px;">
          暂无导入任务，请点击上方按钮或拖入文件
        </div>
      `;
      return;
    }

    this.queueContainer.innerHTML = queue.map(item => `
      <div class="queue-item">
        <div class="queue-item-info">
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="badge ${item.type === 'word' ? 'badge-info' : item.type === 'excel' ? 'badge-success' : item.type === 'pdf' ? 'badge-danger' : 'badge-indigo'}">${item.type.toUpperCase()}</span>
            <span class="queue-item-name truncate" title="${item.name}">${item.name}</span>
          </div>
          <div class="queue-item-meta">
            <span>路径: ${item.path}</span>
            <span>大小: ${item.size}</span>
          </div>
        </div>

        <div style="display:flex; align-items:center; gap:12px;">
          <div style="display:flex; flex-direction:column; align-items:flex-end; gap:3px;">
            <span style="font-size:11px; font-weight:600; color:${item.status === '已入库' ? 'var(--success-text)' : 'var(--text-muted)'};">${item.status}</span>
            <div class="queue-progress-bar-bg">
              <div class="queue-progress-bar-fill" style="width:${item.progress}%;"></div>
            </div>
          </div>
          <span style="width:8px; height:8px; border-radius:50%; background:${item.dot === 'ok' ? 'var(--success-text)' : 'var(--warning-text)'}; flex-shrink:0;"></span>
        </div>
      </div>
    `).join('');
  }
}

window.ImportController = ImportController;
