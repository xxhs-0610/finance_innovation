/**
 * Frontend Utilities - Data Formatters & Sanitizers
 */

export function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function formatScore(score) {
  if (typeof score === 'number') {
    return score.toFixed(3);
  }
  return score || '0.900';
}

export function formatLatency(ms) {
  if (typeof ms === 'number') {
    return `${ms}ms`;
  }
  return ms || '-';
}

export function formatFileSize(bytes) {
  if (typeof bytes !== 'number' || isNaN(bytes)) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(timestamp) {
  const date = timestamp ? new Date(timestamp) : new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function renderInlineCitations(text) {
  if (!text) return '';
  const escaped = escapeHtml(text);
  return escaped.replace(/\[E(\d+)\]/g, '<span class="citation-tag-inline">[E$1]</span>');
}

// Global fallback attachment for script tag usage
if (typeof window !== 'undefined') {
  window.Formatters = {
    escapeHtml,
    formatScore,
    formatLatency,
    formatFileSize,
    formatDate,
    renderInlineCitations
  };
}
