/**
 * RegTrust-RAG Mock Engine & Retrieval Simulator
 * High-fidelity domain knowledge simulator for banking regulations, statistical tables, and refusal mechanisms
 */

class MockRAGService {
  /**
   * Process a user query through the simulated RAG pipeline
   * (Intent Routing -> Hybrid BM25/FAISS -> Rerank -> Grounded Generation -> Guardrail Check)
   */
  static async query(question) {
    const q = question.trim().toLowerCase();

    // 1. Refusal Check (Out-of-domain query)
    if (q.includes('天气') || q.includes('番茄') || q.includes('炒蛋') || q.includes('电影') || q.includes('聊天') || q.includes('旅游') || q.includes('写诗')) {
      await this.sleep(400);
      return {
        status: 'refused',
        conclusion: '【系统触发合规拒答机制】根据现行银行业监管制度与统计报表知识库，未检索到与该问题相关的合法依据。',
        body: `<p><strong>可信拒答说明：</strong></p>
<p>RegTrust-RAG 遵循严格的金融合规底线原则，仅对知识库覆盖的 <em>“制度事实、条款阈值、监管指标、统计报表、业务口径”</em> 五类问题进行回答。对于库外开放域问题或证据不足的提问，系统主动拒绝作答，杜绝大模型金融幻觉与未经授权的事实捏造。</p>`,
        citations: [],
        verification: {
          confidence: 12.0,
          intent: '库外开放域 (触发拒答)',
          numCheck: '不适用',
          hallucinationCheck: '已拦截',
          retrievalLatency: '24ms',
          genLatency: '110ms'
        },
        riskTip: '⚠️ 安全提示：系统检测到该查询超出金融监管知识库范围，已启动安全护栏阻断输出。'
      };
    }

    // 2. Capital Management & Adequacy (资本管理 / 资本充足率)
    if (q.includes('资本') || q.includes('充足率') || q.includes('底线')) {
      await this.sleep(600);
      return {
        status: 'answered',
        conclusion: '根据《商业银行资本管理办法》，商业银行各级资本充足率监管底线分别为：核心一级资本充足率 5%，一级资本充足率 6%，总资本充足率 8%，并须计提 2.5% 的储备资本。',
        body: `<p><strong>详细条文与监管要求剖析：</strong></p>
<ol>
  <li><strong>最低资本要求（底线指标）</strong>：
    <ul>
      <li><strong>核心一级资本充足率</strong>：不得低于 <strong>5%</strong>（通常由实收资本、资本公积、盈余公积和未分配利润构成）；</li>
      <li><strong>一级资本充足率</strong>：不得低于 <strong>6%</strong>；</li>
      <li><strong>资本充足率</strong>：不得低于 <strong>8%</strong>。</li>
    </ul>
  </li>
  <li><strong>储备资本与逆周期资本要求</strong>：
    <ul>
      <li>商业银行必须在最低资本要求之上计提 <strong>2.5%</strong> 的储备资本，全部由核心一级资本满足（因此核心一级资本充足率实际常态要求为 <strong>7.5%</strong>）；</li>
      <li>在宏观信贷过热时期，还需额外满足 <strong>0% - 2.5%</strong> 的逆周期资本要求。</li>
    </ul>
  </li>
  <li><strong>统计报表现状比对</strong>：根据 2025Q2 商业银行主要监管指标表，我国商业银行核心一级资本充足率加权平均值为 <strong>10.85%</strong>，总资本充足率达 <strong>15.53%</strong>，均显著高于监管底线。</li>
</ol>`,
        citations: [
          { id: 'ev_0', title: '商业银行资本管理办法.docx', loc: '第二章 第三十条 (最低资本要求)', chunkId: 'DOC-2024-089-C30', score: 0.965 },
          { id: 'ev_1', title: '商业银行资本管理办法.docx', loc: '第二章 第三十一条 (储备资本)', chunkId: 'DOC-2024-089-C31', score: 0.932 },
          { id: 'ev_2', title: '2025年商业银行主要监管指标情况表.xlsx', loc: '表1 资本充足率行 (2025Q2)', chunkId: 'TBL-2025-001-R12', score: 0.894 }
        ],
        verification: {
          confidence: 98.6,
          intent: '制度事实/条款阈值',
          numCheck: '通过 (5%, 6%, 8%, 2.5%, 10.85%, 15.53%)',
          hallucinationCheck: '无幻觉',
          retrievalLatency: '62ms',
          genLatency: '390ms'
        },
        riskTip: '适用范围提示：本测算规则适用于第一类商业银行。系统重要性银行（D-SIBs）需在此基础上满足额外 0.25% - 1.5% 的附加资本要求。'
      };
    }

    // 3. Statistical Table & Core Indicators (指标 / 2025年 / 不良率 / 拨备)
    if (q.includes('指标') || q.includes('2025') || q.includes('不良') || q.includes('拨备') || q.includes('报表')) {
      await this.sleep(550);
      return {
        status: 'answered',
        conclusion: '2025年商业银行主要监管指标中，不良贷款率维持在 1.56% 稳健水平，拨备覆盖率达 209.4%，流动性覆盖率达 148.2%，整体风险抵补能力充足。',
        body: `<p><strong>2025年二季度银行业核心监管指标结构化提取：</strong></p>
<table style="width:100%; border-collapse:collapse; margin:8px 0; font-size:12px; border:1px solid #e2e8f0;">
  <thead style="background:#f8fafc;">
    <tr>
      <th style="padding:6px 10px; border:1px solid #e2e8f0; text-align:left;">指标名称</th>
      <th style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">2025Q2 实绩</th>
      <th style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">监管标准/预警线</th>
      <th style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">合规状态</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="padding:6px 10px; border:1px solid #e2e8f0;">不良贷款率 (NPL)</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; font-weight:600;">1.56%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">≤ 5.0%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; color:#059669;">达标 (优)</td>
    </tr>
    <tr>
      <td style="padding:6px 10px; border:1px solid #e2e8f0;">拨备覆盖率</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; font-weight:600;">209.4%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">≥ 120%~150%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; color:#059669;">达标 (充裕)</td>
    </tr>
    <tr>
      <td style="padding:6px 10px; border:1px solid #e2e8f0;">资本充足率 (CAR)</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; font-weight:600;">15.53%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">≥ 8.0% (含缓冲10.5%)</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; color:#059669;">达标</td>
    </tr>
    <tr>
      <td style="padding:6px 10px; border:1px solid #e2e8f0;">流动性覆盖率 (LCR)</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; font-weight:600;">148.2%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center;">≥ 100%</td>
      <td style="padding:6px 10px; border:1px solid #e2e8f0; text-align:center; color:#059669;">达标</td>
    </tr>
  </tbody>
</table>`,
        citations: [
          { id: 'ev_2', title: '2025年商业银行主要监管指标情况表.xlsx', loc: 'Sheet1 R10-R30 全行汇总', chunkId: 'TBL-2025-001-ALL', score: 0.972 }
        ],
        verification: {
          confidence: 99.1,
          intent: '统计报表多单元格取数',
          numCheck: '通过 (1.56%, 209.4%, 15.53%, 148.2%)',
          hallucinationCheck: '无幻觉',
          retrievalLatency: '48ms',
          genLatency: '310ms'
        },
        riskTip: '数据口径说明：数据来源于国家金融监督管理总局公开统计季报汇总，为全行业法人机构加权平均数。'
      };
    }

    // 4. Inclusive Finance / Small Business (普惠 / 小微)
    if (q.includes('普惠') || q.includes('小微') || q.includes('贷款')) {
      await this.sleep(580);
      return {
        status: 'answered',
        conclusion: '普惠型小微企业贷款严格限定为单户授信总额 1000 万元及以下的小型微型企业贷款、个体工商户经营性贷款和小微企业主经营性贷款。',
        body: `<p><strong>普惠金融统计制度核心规定归纳：</strong></p>
<ul>
  <li><strong>额度门槛</strong>：单户授信总额（包括各项贷款余额及未使用的授信额度）在 <strong>1000 万元及以下</strong>。超过 1000 万元的划入一般大中型或小微企业大额贷款，不计入普惠考核分母。</li>
  <li><strong>涵盖客群三分类</strong>：
    <ol>
      <li>小型企业、微型企业法人贷款；</li>
      <li>个体工商户用于经营性用途的贷款；</li>
      <li>小微企业主以个人名义借款用于小微企业日常生产经营的贷款。</li>
    </ol>
  </li>
  <li><strong>合规核验重点</strong>：必须核实资金实际流向实体经营领域，严防信贷资金违规流入股市、楼市等受限领域。</li>
</ul>`,
        citations: [
          { id: 'ev_3', title: '银行业普惠金融监管统计制度指引.pdf', loc: '第三章 第八条 (P.18)', chunkId: 'PDF-2023-014-P18', score: 0.941 }
        ],
        verification: {
          confidence: 96.8,
          intent: '业务规章/填报口径',
          numCheck: '通过 (1000万元)',
          hallucinationCheck: '无幻觉',
          retrievalLatency: '71ms',
          genLatency: '340ms'
        },
        riskTip: '填报注意：票据贴现和转贴现业务不纳入普惠型小微企业贷款考核口径。'
      };
    }

    // 5. Default Fallback Grounded Answer
    await this.sleep(500);
    return {
      status: 'answered',
      conclusion: `已为您完成检索。针对“${question}”，系统已在现行监管制度库与统计报表中完成双重校验并组织可信答案。`,
      body: `<p>经混合检索（BM25 关键词匹配 + 向量语义检索），命中文档与条款依据如下：</p>
<ul>
  <li><strong>合规要求</strong>：商业银行开展相关业务必须严格遵守金融监管总局各项管理规定，落实全面风险管理与审慎合规底线；</li>
  <li><strong>报表填报</strong>：涉及监管指标时，须严格按统一统计科目和报告期要求准确填报，确保账实相符；</li>
  <li><strong>溯源校验</strong>：您可以点击下方证据角标或在“证据审查”页面中查阅对应 Word/PDF 原文及 Excel 单元格位置。</li>
</ul>`,
      citations: [
        { id: 'ev_0', title: '商业银行资本管理办法.docx', loc: '第二章 第三十条', chunkId: 'DOC-2024-089-C30', score: 0.88 },
        { id: 'ev_2', title: '2025年商业银行主要监管指标情况表.xlsx', loc: '主要指标表 R12', chunkId: 'TBL-2025-001-R12', score: 0.85 }
      ],
      verification: {
        confidence: 92.4,
        intent: '综合监管问答',
        numCheck: '通过',
        hallucinationCheck: '无幻觉',
        retrievalLatency: '65ms',
        genLatency: '360ms'
      },
      riskTip: '提示：本回答由 RegTrust-RAG 知识库检索生成，建议结合具体业务情景及最新监管公文核验。'
    };
  }

  static sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

window.MockRAGService = MockRAGService;
