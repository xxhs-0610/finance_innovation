/**
 * RegTrust-RAG Module Pipeline & Health Monitoring Controller
 * Visualizes the 5-step end-to-end RAG architecture flow and module integration contracts
 */

class PipelineController {
  constructor() {
    this.container = document.getElementById('pipelineView');
    this.initEvents();
  }

  initEvents() {
    if (this.container) {
      this.container.addEventListener('click', (e) => {
        const step = e.target.closest('.flow-step-card');
        if (step) {
          const stepId = step.dataset.step;
          this.showStepDetail(stepId);
        }
      });
    }
  }

  showStepDetail(stepId) {
    const details = {
      '1': {
        title: '步骤 1：多格式文件统一导入 (File Ingestion)',
        desc: '负责将 Word (.docx)、PDF、Excel (.xlsx) 原始附件与 QA 评测集统一归档至标准目录。',
        input: 'data/raw/nfra_page_attachments_500/ + data/raw/qa/',
        output: '本地统一 Raw 文件池与文件清单 Manifest'
      },
      '2': {
        title: '步骤 2：文档与表格结构化解析 (Document & Table Parsing)',
        desc: '保留条款层级、PDF页码、Excel多级表头与单元格坐标，生成三个交付 JSONL 文件。',
        input: 'data/raw/ 目录下的各格式原始文件',
        output: 'parsed_docs.jsonl, table_evidence.jsonl, doc_meta.jsonl'
      },
      '3': {
        title: '步骤 3：知识库切片与双路索引 (KB Chunking & Indexing)',
        desc: '生成带有完整层级路径元数据的条款/表格 Chunks，并构建 BM25 倒排索引与 FAISS 向量索引。',
        input: 'data/parsed/ 下的结构化数据',
        output: 'clause_chunks.jsonl, table_chunks.jsonl, faiss_index, bm25_index'
      },
      '4': {
        title: '步骤 4：意图路由、混合检索与可信生成 (Retrieval & Generation)',
        desc: '执行查询意图五分类，触发 BM25+FAISS 混合召回与 BGE-Rerank 重排，大模型依据约束提示词生成，执行数字与幻觉校验。',
        input: '用户查询 Query + 索引库',
        output: '结构化答案 JSON + 证据包 + 风险提示 + 拒答判断'
      },
      '5': {
        title: '步骤 5：产品化前端展示与离线评测 (UI & Evaluation)',
        desc: '多会话交互问答、单列证据溯源、原文高亮联动、42条种子问答自动回归评测。',
        input: '后端 API / 检索与生成结果',
        output: '高保真产品界面与评测报告'
      }
    };

    const d = details[stepId];
    if (!d) return;

    window.app.showModal({
      title: `⚙️ ${d.title}`,
      content: `
        <div style="display:flex; flex-direction:column; gap:12px;">
          <p style="font-size:13px; line-height:1.6; color:var(--text-secondary);">${d.desc}</p>
          <div style="background:var(--bg-subtle); padding:10px 14px; border-radius:var(--radius-sm); font-size:12px; display:flex; flex-direction:column; gap:6px;">
            <div><strong>📥 输入数据源:</strong> <code style="font-family:var(--font-code); color:var(--brand-600);">${d.input}</code></div>
            <div><strong>📤 核心交付产物:</strong> <code style="font-family:var(--font-code); color:var(--success-text);">${d.output}</code></div>
          </div>
        </div>
      `
    });
  }
}

window.PipelineController = PipelineController;
