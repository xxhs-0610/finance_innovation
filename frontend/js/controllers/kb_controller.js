/**
 * RegTrust-RAG Knowledge Base Manager Controller (Admin Only)
 * Allows administrators to search, inspect chunks, re-parse, and delete documents in the knowledge base
 */

class KBController {
  constructor() {
    this.tableBody = document.getElementById('kbTableBody');
    this.searchInput = document.getElementById('kbSearchInput');
    this.rebuildIndexBtn = document.getElementById('rebuildIndexBtn');

    this.initEvents();
  }

  initEvents() {
    if (this.searchInput) {
      this.searchInput.addEventListener('input', () => this.render());
    }

    if (this.rebuildIndexBtn) {
      this.rebuildIndexBtn.addEventListener('click', () => {
        if (!this.checkPermission()) return;
        window.app.showToast('正在全量重建 BM25 倒排索引与 FAISS 向量索引...', 'info');
        setTimeout(() => {
          window.app.showToast('全量知识库索引重建完毕，共加载 4,892 个 Chunk！', 'success');
        }, 800);
      });
    }

    // Table action delegation
    if (this.tableBody) {
      this.tableBody.addEventListener('click', (e) => {
        if (!this.checkPermission()) return;

        // View chunks
        const viewBtn = e.target.closest('[data-action="view-chunks"]');
        if (viewBtn) {
          const docId = viewBtn.dataset.docId;
          this.showChunksModal(docId);
          return;
        }

        // Re-parse
        const parseBtn = e.target.closest('[data-action="re-parse"]');
        if (parseBtn) {
          const docId = parseBtn.dataset.docId;
          window.app.showToast(`文档 [${docId}] 已加入增量解析任务队列`, 'success');
          return;
        }

        // Delete
        const delBtn = e.target.closest('[data-action="del-doc"]');
        if (delBtn) {
          const docId = delBtn.dataset.docId;
          if (confirm(`确定要从知识库中删除文档 [${docId}] 及其所有关联 Chunk 吗？`)) {
            window.appState.deleteKbDoc(docId);
            window.app.showToast(`文档 [${docId}] 已从知识库移除`, 'warning');
          }
        }
      });
    }

    window.appState.subscribe('kbUpdated', () => this.render());
    this.render();
  }

  checkPermission() {
    if (window.appState.get('role') !== 'admin') {
      window.app.showToast('⚠️ 权限不足：仅管理员具备知识库管理权限', 'warning');
      return false;
    }
    return true;
  }

  render() {
    const docs = window.appState.get('kbDocuments') || [];
    const query = (this.searchInput?.value || '').trim().toLowerCase();

    const filtered = docs.filter(d =>
      d.title.toLowerCase().includes(query) ||
      d.docNo.toLowerCase().includes(query) ||
      d.category.toLowerCase().includes(query)
    );

    if (!this.tableBody) return;

    if (filtered.length === 0) {
      this.tableBody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align:center; padding:30px; color:var(--text-muted);">未找到匹配的知识库文档</td>
        </tr>
      `;
      return;
    }

    this.tableBody.innerHTML = filtered.map(d => `
      <tr>
        <td style="font-family:var(--font-code); font-weight:600; color:var(--brand-600);">${d.id}</td>
        <td>
          <span style="font-weight:600; color:var(--text-primary); display:block;">${d.title}</span>
          <span style="font-size:11px; color:var(--text-muted);">${d.docNo}</span>
        </td>
        <td><span class="badge ${d.type === 'Word' ? 'badge-info' : d.type === 'Excel' ? 'badge-success' : 'badge-danger'}">${d.type}</span></td>
        <td><span class="badge badge-indigo">${d.chunks} Chunks</span></td>
        <td>${d.category}</td>
        <td><span class="badge badge-success">✓ ${d.status}</span></td>
        <td>
          <div style="display:flex; gap:4px;">
            <button class="btn btn-sm" data-action="view-chunks" data-doc-id="${d.id}" title="查看切片">切片</button>
            <button class="btn btn-sm" data-action="re-parse" data-doc-id="${d.id}" title="重新解析">重构</button>
            <button class="btn btn-sm btn-ghost" data-action="del-doc" data-doc-id="${d.id}" style="color:var(--danger-text);" title="删除">
              <svg class="icon icon-sm" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          </div>
        </td>
      </tr>
    `).join('');
  }

  showChunksModal(docId) {
    const doc = (window.appState.get('kbDocuments') || []).find(d => d.id === docId);
    if (!doc) return;

    window.app.showModal({
      title: `🧩 文档 [${doc.title}] 结构化切片与元数据详情`,
      content: `
        <div style="display:flex; flex-direction:column; gap:10px;">
          <div style="font-size:12px; color:var(--text-muted);">
            文档ID: <strong>${doc.id}</strong> | 格式: <strong>${doc.type}</strong> | 切片总数: <strong>${doc.chunks}</strong> | 分类: <strong>${doc.category}</strong>
          </div>
          <div style="display:flex; flex-direction:column; gap:8px; max-height:360px; overflow-y:auto;">
            <div style="border:1px solid var(--border-light); border-radius:6px; padding:10px; background:#fafbff;">
              <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:4px;">
                <span class="badge badge-indigo">Chunk #001 · 条款层级</span>
                <span style="color:var(--text-muted);">Embedding 768维 · BM25已索引</span>
              </div>
              <div style="font-size:12px; line-height:1.6;">【第二章 资本充足率计算与监管要求】第三十条 商业银行各级资本充足率不得低于如下正常监管要求：核心一级5%，一级6%，资本充足率8%...</div>
            </div>
            <div style="border:1px solid var(--border-light); border-radius:6px; padding:10px; background:#fafbff;">
              <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:4px;">
                <span class="badge badge-indigo">Chunk #002 · 缓冲资本</span>
                <span style="color:var(--text-muted);">Embedding 768维 · BM25已索引</span>
              </div>
              <div style="font-size:12px; line-height:1.6;">【第二章 资本充足率计算与监管要求】第三十一条 商业银行应当在最低资本要求的基础上计提储备资本，储备资本要求为风险加权资产的2.5%...</div>
            </div>
          </div>
        </div>
      `
    });
  }
}

window.KBController = KBController;
