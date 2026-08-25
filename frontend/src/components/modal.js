/**
 * Reusable Modal Dialog Component
 */

export class ModalComponent {
  static init() {
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

  static show({ title, content }) {
    this.init();
    const backdrop = document.getElementById('modal-backdrop');
    const titleEl = document.getElementById('modalTitle');
    const bodyEl = document.getElementById('modalBody');

    if (backdrop && titleEl && bodyEl) {
      titleEl.innerHTML = title || '详情预览';
      bodyEl.innerHTML = content || '';
      backdrop.classList.remove('hidden');
    }
  }

  static hide() {
    const backdrop = document.getElementById('modal-backdrop');
    if (backdrop) backdrop.classList.add('hidden');
  }
}

if (typeof window !== 'undefined') {
  window.ModalComponent = ModalComponent;
}
