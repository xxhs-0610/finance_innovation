/**
 * Reusable Toast Notification Component
 */

export class ToastComponent {
  static show(message, type = 'info', duration = 2800) {
    const container = document.getElementById('toast-container') || this.createContainer();

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
    }, duration);
  }

  static createContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    return container;
  }
}

if (typeof window !== 'undefined') {
  window.ToastComponent = ToastComponent;
}
