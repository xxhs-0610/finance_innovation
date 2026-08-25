/**
 * RegTrust-RAG Evidence Review Controller
 * Strict Single-Column layout for citations & dynamic original document preview container below
 */

class EvidenceController {
  constructor() {
    this.listContainer = document.getElementById('evidenceListContainer');
    this.previewContainer = document.getElementById('docPreviewContainer');
    this.previewTitle = document.getElementById('previewDocTitle');
    this.previewMeta = document.getElementById('previewDocMeta');
    this.previewBody = document.getElementById('previewDocBody');
    this.openFullDocBtn = document.getElementById('openFullDocBtn');

    this.initEvents();
  }

  initEvents() {
    // List item delegation
    if (this.listContainer) {
      this.listContainer.addEventListener('click', (e) => {
        // Check "打开原文档" button
        const openBtn = e.target.closest('[data-action="open-doc"]');
        if (openBtn) {
          const card = openBtn.closest('.evidence-card');
          const index = parseInt(card.dataset.index, 10);
          this.showFullDocumentModal(index);
          return;
        }

        // Card click -> switch preview
        const card = e.target.closest('.evidence-card');
        if (card) {
          const index = parseInt(card.dataset.index, 10);
          window.appState.setActiveEvidence(index);
        }
      });
    }

    // Open full doc modal from preview topbar
    if (this.openFullDocBtn) {
      this.openFullDocBtn.addEventListener('click', () => {
        const idx = window.appState.get('activeEvidenceIndex');
        this.showFullDocumentModal(idx);
      });
    }

    // State listeners
    window.appState.subscribe('evidenceChanged', (index) => {
      this.renderListSelection(index);
      this.renderPreview(index);
    });

    this.render();
  }

  render() {
    const list = window.appState.get('evidenceList') || [];
    const activeIndex = window.appState.get('activeEvidenceIndex') || 0;

    if (!this.listContainer) return;

    // 1. Render Strict Single-Column Evidence Cards
    this.listContainer.innerHTML = list.map((item, idx) => `
      <div class="evidence-card ${idx === activeIndex ? 'active' : ''}" data-index="${idx}">
        <div class="evidence-card-header">
          <div class="evidence-filename">
            <span class="badge ${item.type === 'word' ? 'badge-info' : item.type === 'excel' ? 'badge-success' : 'badge-danger'}">
              ${item.type === 'word' ? 'Word 条款' : item.type === 'excel' ? 'Excel 统计表' : 'PDF 章节'}
            </span>
            <span>${item.title}</span>
          </div>
          <span class="badge badge-success">置信度 ${item.score}</span>
        </div>

        <!-- Small text for original quote -->
        <div class="evidence-quote">
          <strong>原文依据：</strong>${item.quote}
        </div>

        <!-- Small text for location metadata -->
        <div class="evidence-loc-meta">
          <span>📍 <strong>定位信息:</strong> ${item.loc}</span>
          <span>📁 <strong>文号:</strong> ${item.docNo}</span>
          <span>🏛️ <strong>发文机构:</strong> ${item.promulgation}</span>
        </div>

        <div class="evidence-actions-row">
          <button class="btn btn-sm btn-primary" data-action="open-doc">
            <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
            打开该依据的原文档
          </button>
        </div>
      </div>
    `).join('');

    this.renderPreview(activeIndex);
  }

  renderListSelection(activeIndex) {
    if (!this.listContainer) return;
    const cards = this.listContainer.querySelectorAll('.evidence-card');
    cards.forEach((card, idx) => {
      card.classList.toggle('active', idx === activeIndex);
    });
  }

  renderPreview(index) {
    const list = window.appState.get('evidenceList') || [];
    const item = list[index] || list[0];
    if (!item) return;

    if (this.previewTitle) {
      this.previewTitle.innerHTML = `
        <span class="badge ${item.type === 'word' ? 'badge-info' : item.type === 'excel' ? 'badge-success' : 'badge-danger'}">${item.type.toUpperCase()}</span>
        <span>${item.title}</span>
      `;
    }

    if (this.previewMeta) {
      this.previewMeta.textContent = `${item.promulgation} · ${item.docNo} · ${item.validity}`;
    }

    if (this.previewBody) {
      let formattedSnippet = item.previewSnippet.replace(
        item.highlightText,
        `<div class="doc-preview-highlight-box">📌 <strong>命中的核心证据条款/单元格：</strong><br/>${item.highlightText}</div>`
      );

      this.previewBody.innerHTML = `
        <div style="font-family:var(--font-code); white-space:pre-wrap; font-size:12px; line-height:1.7;">${formattedSnippet}</div>
      `;
    }

    this.syncRightSidebar(item);
  }

  async showFullDocumentModal(index) {
    const list = window.appState.get('evidenceList') || [];
    const item = list[index] || list[0];
    if (!item) return;

    window.app.showModal({
      title: `📄 ${item.fullDocTitle || item.title}`,
      content: `
        <div style="display:flex; flex-direction:column; gap:14px; min-width:550px;">
          <div style="background:var(--bg-subtle); padding:10px 14px; border-radius:var(--radius-sm); font-size:12px; display:grid; grid-template-columns:1fr 1fr; gap:8px;">
            <div><strong>发文机关:</strong> ${item.promulgation || '国家金融监督管理总局'}</div>
            <div><strong>文件字号:</strong> ${item.docNo || '-'}</div>
            <div><strong>时效状态:</strong> <span class="badge badge-success">${item.validity || '现行有效'}</span></div>
            <div><strong>命中位置:</strong> ${item.loc || '正文条款'}</div>
          </div>
          <div style="background:#eef2ff; border:1px solid #c7d2fe; border-radius:var(--radius-sm); padding:10px 14px; font-size:12px; color:#3730a3;">
            📌 <strong>命中的核心证据依据：</strong>
            <div style="margin-top:4px; font-family:var(--font-code); color:#1e1b4b;">${item.quote || item.highlightText || ''}</div>
          </div>
          <div id="fullDocLoadingPlaceholder" style="padding:20px; text-align:center; color:var(--text-muted); font-size:12px;">
            ⏳ 正在从知识库调取该原文档全部章节与全文...
          </div>
          <div id="fullDocContentContainer" style="display:none; border:1px solid var(--border-light); border-radius:var(--radius-sm); padding:14px; background:#fff; font-family:var(--font-code); white-space:pre-wrap; font-size:12px; max-height:360px; overflow-y:auto; line-height:1.7;">
          </div>
        </div>
      `
    });

    try {
      const docData = await window.APIService?.getDocPreview(item.docId, item.title);
      const loadingEl = document.getElementById('fullDocLoadingPlaceholder');
      const contentEl = document.getElementById('fullDocContentContainer');

      if (loadingEl && contentEl) {
        loadingEl.style.display = 'none';
        contentEl.style.display = 'block';

        let fullText = docData?.full_text || item.previewSnippet || item.quote;
        const totalChunks = docData?.total_chunks || 1;

        if (item.quote && fullText.includes(item.quote)) {
          fullText = fullText.replace(
            item.quote,
            `\n>>> [📌 命中依据位置] >>>\n${item.quote}\n<<< [命中依据结束] <<<\n`
          );
        }

        contentEl.textContent = fullText;
        if (contentEl.parentElement) {
          const headerInfo = document.createElement('div');
          headerInfo.style.cssText = 'font-size:11px; color:var(--text-muted); margin-bottom:-4px;';
          headerInfo.textContent = `共加载原文档 ${totalChunks} 个结构化章节/条款切片：`;
          contentEl.parentElement.insertBefore(headerInfo, contentEl);
        }
      }
    } catch (e) {
      console.warn('Failed to load full document context:', e);
    }
  }

  syncRightSidebar(item) {
    const el = document.getElementById('evidenceRightContext');
    if (!el || !item) return;

    el.innerHTML = `
      <div style="font-size:12px; font-weight:600; color:var(--text-primary); margin-bottom:4px;">当前审查文档元数据</div>
      <div style="background:var(--bg-subtle); border-radius:var(--radius-sm); padding:10px; font-size:11.5px; display:flex; flex-direction:column; gap:6px;">
        <div><strong>文档ID:</strong> ${item.docId}</div>
        <div><strong>发文机构:</strong> ${item.promulgation}</div>
        <div><strong>文件编号:</strong> ${item.docNo}</div>
        <div><strong>时效性:</strong> <span class="badge badge-success" style="font-size:10.5px;">${item.validity}</span></div>
        <div><strong>匹配度得分:</strong> <strong style="color:var(--brand-600);">${item.score}</strong></div>
      </div>
    `;
  }
}

window.EvidenceController = EvidenceController;
