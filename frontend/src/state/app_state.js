/**
 * RegTrust-RAG Global State Store & Event Bus
 * Provides central reactive state for Sessions, Role Permissions, Knowledge Base, Evidence, and Pipeline
 */

class AppState {
  constructor() {
    this.listeners = new Map();

    // Default Initial State
    this.state = {
      role: 'admin', // 'admin' | 'user'
      view: 'chat',  // 'chat' | 'import' | 'kb' | 'evidence' | 'pipeline'
      activeSessionId: 'sess_1',
      activeEvidenceIndex: 0,

      // Sessions List
      sessions: [
        {
          id: 'sess_1',
          title: '商业银行资本管理要求',
          topic: '问答：资本充足率监管底线与缓冲资本',
          updated: '10:24',
          turns: 3,
          messages: [
            {
              id: 'msg_1_1',
              role: 'user',
              text: '商业银行应当如何管理资本？核心一级资本充足率和总资本充足率的监管底线分别是多少？',
              timestamp: '10:22'
            },
            {
              id: 'msg_1_2',
              role: 'assistant',
              conclusion: '商业银行资本管理须遵循审慎性原则，各级资本充足率不得低于法定监管底线（核心一级5%、一级6%、资本充足率8%），并在此基础上计提储备资本与逆周期资本。',
              body: `<p>根据现行《商业银行资本管理办法》及配套监管指引，商业银行的资本管理要求主要包括以下要点：</p>
<ol>
  <li><strong>资本充足率监管底线</strong>：商业银行各级资本充足率不得低于以下底线要求：
    <ul>
      <li><strong>核心一级资本充足率</strong>：不得低于 <strong>5%</strong>；</li>
      <li><strong>一级资本充足率</strong>：不得低于 <strong>6%</strong>；</li>
      <li><strong>资本充足率（总资本）</strong>：不得低于 <strong>8%</strong>。</li>
    </ul>
  </li>
  <li><strong>缓冲与附加资本要求</strong>：在上述底线之上，商业银行还应当计提 <strong>2.5%</strong> 的储备资本（由核心一级资本来满足），特定时期根据宏观审慎监管要求计提 <strong>0% - 2.5%</strong> 的逆周期资本。</li>
  <li><strong>资本规划与动态管理</strong>：银行应当建立内部资本充足评估程序（ICAAP），将资本规划与全面风险管理、资产负债配置策略紧密结合。</li>
</ol>`,
              citations: [
                { id: 'ev_0', title: '商业银行资本管理办法.docx', loc: '第二章 第三十条', chunkId: 'DOC-2024-089-C30', score: 0.96 },
                { id: 'ev_1', title: '商业银行资本管理办法.docx', loc: '第二章 第三十一条 (储备资本)', chunkId: 'DOC-2024-089-C31', score: 0.93 },
                { id: 'ev_2', title: '2025年商业银行主要监管指标情况表.xlsx', loc: '表1 行12 (资本充足率)', chunkId: 'TBL-2025-001-R12', score: 0.89 }
              ],
              verification: {
                confidence: 97.6,
                intent: '制度事实/指标规定',
                numCheck: '通过 (5%, 6%, 8%, 2.5%)',
                hallucinationCheck: '无幻觉',
                retrievalLatency: '68ms',
                genLatency: '380ms'
              },
              riskTip: '注：上述标准适用于我国第一类商业银行。系统重要性银行需在此基础上额外满足附加资本要求（0.25% - 1.5%）。',
              timestamp: '10:24'
            }
          ]
        },
        {
          id: 'sess_2',
          title: '2025主要监管指标分析',
          topic: '表格取数：不良贷款率与拨备覆盖率',
          updated: '09:40',
          turns: 1,
          messages: [
            {
              id: 'msg_2_1',
              role: 'user',
              text: '2025年商业银行主要监管指标情况表里，资产质量与风险抵补核心指标表现如何？',
              timestamp: '09:38'
            },
            {
              id: 'msg_2_2',
              role: 'assistant',
              conclusion: '2025年主要监管指标显示银行业整体资产质量稳健，不良贷款率保持在合理区间，拨备覆盖率充足，风险抵补能力持续处于监管标准之上。',
              body: `<p>根据《2025年商业银行主要监管指标情况表（季度汇总）》报表取数分析：</p>
<ul>
  <li><strong>不良贷款率（NPL Ratio）</strong>：商业银行合计为 <strong>1.56%</strong>，较上季度微降 0.02 个百分点，显著优于监管 5% 的预警线。</li>
  <li><strong>拨备覆盖率（Provision Coverage）</strong>：达 <strong>209.4%</strong>，优于 120%~150% 的监管底线，具备充足的信用风险缓冲垫。</li>
  <li><strong>流动性比例</strong>：流动性覆盖率（LCR）保持在 <strong>148.2%</strong>，符合 >100% 的合规要求。</li>
</ul>`,
              citations: [
                { id: 'ev_2', title: '2025年商业银行主要监管指标情况表.xlsx', loc: '主要指标表 行18-24', chunkId: 'TBL-2025-001-R18', score: 0.95 }
              ],
              verification: {
                confidence: 98.4,
                intent: '表格取数/统计指标',
                numCheck: '通过 (1.56%, 209.4%, 148.2%)',
                hallucinationCheck: '无幻觉',
                retrievalLatency: '52ms',
                genLatency: '320ms'
              },
              riskTip: '提示：不同类型机构（大型商业银行、股份制银行、城商行、农商行）细分指标存在分化，请结合分机构报表查阅。',
              timestamp: '09:40'
            }
          ]
        },
        {
          id: 'sess_3',
          title: '普惠小微贷款统计口径',
          topic: '制度与业务：普惠型小微企业贷款定义',
          updated: '昨日 17:30',
          turns: 1,
          messages: [
            {
              id: 'msg_3_1',
              role: 'user',
              text: '银行业普惠型小微企业贷款的统计口径与填报范围是什么？',
              timestamp: '昨日 17:28'
            },
            {
              id: 'msg_3_2',
              role: 'assistant',
              conclusion: '普惠型小微企业贷款统计口径指单户授信总额 1000 万元及以下的小微企业贷款，包含个体工商户和小微企业主经营性贷款。',
              body: `<p>依据原银保监会普惠金融统计口径与填报指引：</p>
<ol>
  <li><strong>授信额度限制</strong>：单户授信总额（含贷款、透支、承兑等）在 <strong>1000 万元及以下</strong>。</li>
  <li><strong>统计主体范畴</strong>：
    <ul>
      <li>符合《中小企业划型标准规定》的小型和微型企业贷款；</li>
      <li>个体工商户经营性贷款；</li>
      <li>小微企业主经营性贷款。</li>
    </ul>
  </li>
  <li><strong>监管考核要求</strong>：持续保持“两增”或差异化考核目标，实现贷款增速不低于各项贷款平均增速。</li>
</ol>`,
              citations: [
                { id: 'ev_3', title: '银行业普惠金融监管统计制度指引.pdf', loc: '第三章 统计指标释义 第8条', chunkId: 'PDF-2023-014-P18', score: 0.92 }
              ],
              verification: {
                confidence: 95.8,
                intent: '业务制度/统计口径',
                numCheck: '通过 (1000万元)',
                hallucinationCheck: '无幻觉',
                retrievalLatency: '74ms',
                genLatency: '350ms'
              },
              riskTip: '注意：不含贴现及转贴现业务，且剔除已核销但未剥离的呆账。',
              timestamp: '昨日 17:30'
            }
          ]
        }
      ],

      // Evidence Store (Single-Column Presentation)
      evidenceList: [
        {
          id: 'ev_0',
          title: '商业银行资本管理办法（试行）.docx',
          type: 'word',
          docId: 'DOC-2024-089',
          score: '0.965',
          loc: '第二章 资本充足率计算与监管要求 · 第三十条',
          quote: '第三十条 商业银行各级资本充足率不得低于如下正常监管要求：核心一级资本充足率不得低于5%，一级资本充足率不得低于6%，资本充足率不得低于8%。',
          fullDocTitle: '国家金融监督管理总局令 2023年第4号 - 商业银行资本管理办法',
          promulgation: '国家金融监督管理总局',
          docNo: '金规〔2023〕4号',
          validity: '现行有效',
          previewSnippet: `【文档正文片段 · 节选自 第二章 资本充足率计算与监管要求】
第二十九条 商业银行应当按照本办法的规定计算并满足各级资本充足率监管要求。
第三十条 商业银行各级资本充足率不得低于如下正常监管要求：
  (一) 核心一级资本充足率不得低于 5%；
  (二) 一级资本充足率不得低于 6%；
  (三) 资本充足率不得低于 8%。
第三十一条 商业银行应当在最低资本要求的基础上计提储备资本。储备资本要求为风险加权资产的 2.5%，由核心一级资本来满足。
第三十二条 特定情况下，商业银行应当按照监管部门的规定计提逆周期资本。逆周期资本要求为风险加权资产的 0-2.5%，由核心一级资本来满足。`,
          highlightText: '第三十条 商业银行各级资本充足率不得低于如下正常监管要求：(一) 核心一级资本充足率不得低于 5%；(二) 一级资本充足率不得低于 6%；(三) 资本充足率不得低于 8%。'
        },
        {
          id: 'ev_1',
          title: '商业银行资本管理办法（试行）.docx',
          type: 'word',
          docId: 'DOC-2024-089',
          score: '0.932',
          loc: '第二章 资本充足率计算与监管要求 · 第三十一条',
          quote: '第三十一条 商业银行应当在最低资本要求的基础上计提储备资本。储备资本要求为风险加权资产的2.5%，由核心一级资本来满足。',
          fullDocTitle: '国家金融监督管理总局令 2023年第4号 - 商业银行资本管理办法',
          promulgation: '国家金融监督管理总局',
          docNo: '金规〔2023〕4号',
          validity: '现行有效',
          previewSnippet: `第三十一条 商业银行应当在最低资本要求的基础上计提储备资本。储备资本要求为风险加权资产的 2.5%，由核心一级资本来满足。
第三十二条 在宏观经济过热或信贷快速扩张时期，国家金融监督管理总局有权要求商业银行计提逆周期资本。逆周期资本要求为风险加权资产的 0-2.5%，由核心一级资本来满足。`,
          highlightText: '储备资本要求为风险加权资产的 2.5%，由核心一级资本来满足。'
        },
        {
          id: 'ev_2',
          title: '2025年商业银行主要监管指标情况表.xlsx',
          type: 'excel',
          docId: 'TBL-2025-001',
          score: '0.948',
          loc: 'Sheet: 主要监管指标情况汇总 · 行: R12 资本充足率 · 单元格: C12:E12',
          quote: '2025Q2 商业银行（加权平均）：核心一级资本充足率 10.85%，一级资本充足率 12.38%，资本充足率 15.53%，拨备覆盖率 209.4%，不良贷款率 1.56%。',
          fullDocTitle: '2025年二季度银行业主要监管指标统计数据汇总表',
          promulgation: '统计与风险监测司',
          docNo: 'NFRA-STAT-2025-Q2',
          validity: '最新报表',
          previewSnippet: `【Excel 报表结构化数据片段】
报表名称：2025年商业银行主要监管指标情况表 (季报汇总)
期间：2025年第二季度 (2025Q2) | 币种：人民币 | 单位：%
+-----------------------------+---------+---------+---------+
| 指标项目 (Metric)           | 2024Q4  | 2025Q1  | 2025Q2  |
+-----------------------------+---------+---------+---------+
| 一、资本充足率指标          |         |         |         |
|   1. 核心一级资本充足率     | 10.74%  | 10.79%  | 10.85%  |
|   2. 一级资本充足率         | 12.26%  | 12.31%  | 12.38%  |
|   3. 资本充足率             | 15.42%  | 15.48%  | 15.53%  |
| 二、资产质量与风险抵补      |         |         |         |
|   4. 不良贷款率 (NPL)       |  1.59%  |  1.58%  |  1.56%  |
|   5. 拨备覆盖率             | 206.8%  | 208.1%  | 209.4%  |
|   6. 贷款拨备率             |  3.29%  |  3.29%  |  3.27%  |
+-----------------------------+---------+---------+---------+`,
          highlightText: '| 1. 核心一级资本充足率 | 10.74% | 10.79% | 10.85% | / | 3. 资本充足率 | 15.42% | 15.48% | 15.53% |'
        },
        {
          id: 'ev_3',
          title: '银行业普惠金融监管统计制度指引.pdf',
          type: 'pdf',
          docId: 'PDF-2023-014',
          score: '0.916',
          loc: '第三章 统计指标释义与填报说明 · 第八条 (P.18)',
          quote: '第八条 普惠型小微企业贷款是指单户授信总额1000万元及以下的小型和微型企业贷款、个体工商户经营性贷款以及小微企业主经营性贷款。',
          fullDocTitle: '中国银保监会办公厅关于印发银行业普惠金融监管统计制度的通知',
          promulgation: '银保监会办公厅',
          docNo: '银保监办发〔2020〕15号',
          validity: '现行有效',
          previewSnippet: `【PDF 解析文本块 · 页码: P.18】
第三章 普惠金融重点领域指标定义与填报说明
第七条 各银行业金融机构应按照“实质重于形式”的原则，严格审核客户资质与授信额度。
第八条 普惠型小微企业贷款是指单户授信总额在 1000 万元及以下（含 1000 万元）的下列贷款：
  (一) 符合《统计上大中小微型企业划分办法(2017)》的小型和微型企业贷款；
  (二) 个体工商户经营性贷款；
  (三) 小微企业主以个人名义申请、用于小微企业合法生产经营的贷款。`,
          highlightText: '第八条 普惠型小微企业贷款是指单户授信总额在 1000 万元及以下（含 1000 万元）的下列贷款'
        }
      ],

      // Import Workbench File Queue
      importQueue: [
        { id: 'q_1', name: '商业银行资本管理办法（试行）.docx', type: 'word', size: '2.4 MB', path: 'data/raw/nfra_page_attachments_500/', status: '已入库', progress: 100, dot: 'ok' },
        { id: 'q_2', name: '2025年商业银行主要监管指标情况表.xlsx', type: 'excel', size: '1.8 MB', path: 'data/raw/nfra_page_attachments_500/', status: '已入库', progress: 100, dot: 'ok' },
        { id: 'q_3', name: '银行业普惠金融监管统计制度指引.pdf', type: 'pdf', size: '4.1 MB', path: 'data/raw/nfra_page_attachments_500/', status: '已入库', progress: 100, dot: 'ok' },
        { id: 'q_4', name: '银行业金融机构流动性风险管理办法.docx', type: 'word', size: '1.9 MB', path: 'data/raw/nfra_page_attachments_500/', status: '待解析', progress: 0, dot: 'wait' },
        { id: 'q_5', name: 'QA_银行业监管与报表评测集_42题.xlsx', type: 'qa', size: '520 KB', path: 'data/raw/qa/', status: '已校验', progress: 100, dot: 'ok' }
      ],

      // Knowledge Base Table (Admin View)
      kbDocuments: [
        { id: 'DOC-2024-089', title: '商业银行资本管理办法（试行）.docx', type: 'Word', chunks: 142, docNo: '金规〔2023〕4号', category: '资本与风险', updated: '2026-08-15', status: '已就绪' },
        { id: 'TBL-2025-001', title: '2025年商业银行主要监管指标情况表.xlsx', type: 'Excel', chunks: 86, docNo: 'NFRA-STAT-2025-Q2', category: '监管统计报表', updated: '2026-08-16', status: '已就绪' },
        { id: 'PDF-2023-014', title: '银行业普惠金融监管统计制度指引.pdf', type: 'PDF', chunks: 98, docNo: '银保监办发〔2020〕15号', category: '普惠金融', updated: '2026-08-14', status: '已就绪' },
        { id: 'DOC-2023-042', title: '商业银行流动性风险管理办法.docx', type: 'Word', chunks: 116, docNo: '银保监会令2018年第3号', category: '流动性管理', updated: '2026-08-12', status: '已就绪' },
        { id: 'TBL-2024-004', title: '银行业金融机构资产负债季度统计表.xlsx', type: 'Excel', chunks: 210, docNo: 'STAT-2024-Q4', category: '资产负债表', updated: '2026-08-10', status: '已就绪' },
        { id: 'PDF-2024-002', title: '银行业保险业绿色金融指引.pdf', type: 'PDF', chunks: 64, docNo: '银保监发〔2022〕15号', category: '绿色金融', updated: '2026-08-08', status: '已就绪' }
      ],

      // Pipeline & Indexes Metrics
      pipelineStats: {
        rawFiles: 492,
        totalDocs: 500,
        totalChunks: 125166,
        clauseChunks: 22880,
        tableChunks: 102286,
        vectorDim: 512,
        vectorModel: 'Model/bge-small-zh-v1.5',
        indexesDir: 'indexes/kb_rebuild',
        totalStorage: '563.1 MB',
        seedQAPassing: '42 / 42 (100%)',
        avgLatencyRetrieval: '48 ms',
        avgLatencyGen: '320 ms'
      },
      indexesOverview: null
    };
  }

  // Event Subscription
  subscribe(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }

  notify(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach(cb => cb(data));
    }
  }

  // Getters
  get(key) {
    return this.state[key];
  }

  // State Mutators
  setRole(role) {
    this.state.role = role;
    this.notify('roleChanged', role);
  }

  setView(view) {
    this.state.view = view;
    this.notify('viewChanged', view);
  }

  setActiveSession(sessionId) {
    this.state.activeSessionId = sessionId;
    this.notify('sessionChanged', sessionId);
  }

  getActiveSession() {
    return this.state.sessions.find(s => s.id === this.state.activeSessionId) || this.state.sessions[0];
  }

  createSession() {
    const nextNum = this.state.sessions.length + 1;
    const newId = `sess_${Date.now()}`;
    const newSession = {
      id: newId,
      title: `新对话窗口 ${nextNum}`,
      topic: '空白会话，请输入您的监管制度或报表问题',
      updated: '刚刚',
      turns: 0,
      messages: []
    };
    this.state.sessions.unshift(newSession);
    this.state.activeSessionId = newId;
    this.notify('sessionListUpdated', this.state.sessions);
    this.notify('sessionChanged', newId);
    return newSession;
  }

  addMessageToActiveSession(message) {
    const session = this.getActiveSession();
    if (!session) return;
    session.messages.push(message);
    session.turns = Math.ceil(session.messages.length / 2);
    session.updated = '刚刚';
    if (session.messages.length === 1 && message.role === 'user') {
      session.title = message.text.slice(0, 14) + (message.text.length > 14 ? '...' : '');
    }
    this.notify('sessionUpdated', session);
  }

  clearActiveSession() {
    const session = this.getActiveSession();
    if (!session) return;
    session.messages = [];
    session.turns = 0;
    this.notify('sessionUpdated', session);
  }

  setActiveEvidence(index) {
    this.state.activeEvidenceIndex = index;
    this.notify('evidenceChanged', index);
  }

  addImportFile(fileItem) {
    this.state.importQueue.unshift(fileItem);
    this.notify('queueUpdated', this.state.importQueue);
  }

  deleteKbDoc(docId) {
    this.state.kbDocuments = this.state.kbDocuments.filter(d => d.id !== docId);
    this.notify('kbUpdated', this.state.kbDocuments);
  }
}

// Global Singleton
window.appState = new AppState();
