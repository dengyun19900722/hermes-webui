// -- WorkBuddy empty-conversation launchpad ---------------------------------
// Runs inside #emptyState and keeps the normal profile, workspace, composer,
// and send lifecycle intact. It selects intent only; it never sends a turn.

(function(){
  'use strict';

  const STORAGE_CAPABILITY = 'hermes-workbuddy-session-guide-capability-v2';
  const STORAGE_CASE_BATCH = 'hermes-workbuddy-session-guide-case-batch-v2';
  const STORAGE_DICTIONARY = 'hermes-workbuddy-session-guide-dictionary-v1';
  const DEFAULT_CAPABILITY = 'asset';
  const DEFAULT_AGENT = 'zk';
  const CASE_BATCH_SIZE = 2;

  const GUIDE_TRANSLATION_DICTIONARY = {
    agents: {
      default: {zh:'默认', en:'Default'},
      zk: {zh:'zk业务线', en:'ZK business line'},
      deployer: {zh:'发布智能体', en:'Deployment agent'},
      developer: {zh:'研发智能体', en:'Development agent'},
      requirement: {zh:'需求智能体', en:'Requirements agent'},
      tester: {zh:'测试智能体', en:'Testing agent'},
      'ui-designer': {zh:'UI 设计智能体', en:'UI design agent'},
      query: {zh:'查询业务线', en:'Query business line'},
      search: {zh:'查询业务线', en:'Query business line'},
      data: {zh:'数匠中台', en:'Data platform'},
      shuj: {zh:'数匠中台', en:'Data platform'}
    },
    capabilities: {
      '(general)': {zh:'通用', en:'General'},
      general: {zh:'通用', en:'General'},
      diagnosis: {zh:'故障诊断', en:'Troubleshooting'},
      inspection: {zh:'日常巡检', en:'Daily inspection'},
      asset: {zh:'资产管理', en:'Asset management'},
      assets: {zh:'资产管理', en:'Asset management'},
      report: {zh:'运维报告生成', en:'Ops reports'},
      knowledge: {zh:'知识库管理', en:'Knowledge base'},
      documents: {zh:'文档处理', en:'Document processing'},
      document: {zh:'文档处理', en:'Document processing'},
      operations: {zh:'运维', en:'Operations'},
      devops: {zh:'运维', en:'DevOps'},
      monitoring: {zh:'监控巡检', en:'Monitoring'},
      deployment: {zh:'发布部署', en:'Deployment'},
      development: {zh:'研发开发', en:'Development'},
      coding: {zh:'代码开发', en:'Coding'},
      testing: {zh:'测试验证', en:'Testing'},
      ui: {zh:'UI 设计', en:'UI design'},
      design: {zh:'设计', en:'Design'},
      research: {zh:'资料检索', en:'Research'},
      papers: {zh:'论文检索', en:'Papers'},
      academic: {zh:'学术资料', en:'Academic'},
      browser: {zh:'浏览器操作', en:'Browser automation'},
      data: {zh:'数据处理', en:'Data processing'},
      graph: {zh:'关系图谱', en:'Graph'},
      memory: {zh:'记忆管理', en:'Memory'}
    },
    skills: {
      shell_inspection_v3: {
        label: {zh:'巡检 TCMS 程序', en:'Inspect TCMS program'},
        desc: {zh:'检查进程、端口、资源占用与关键指标。', en:'Check processes, ports, resource usage, and key metrics.'}
      },
      shell_inspection_v2: {
        label: {zh:'巡检 TCMS 程序', en:'Inspect TCMS program'},
        desc: {zh:'执行 Shell 巡检并汇总异常。', en:'Run shell inspection and summarize anomalies.'}
      },
      shell_inspection: {
        label: {zh:'Shell 巡检', en:'Shell inspection'},
        desc: {zh:'执行命令行巡检并整理异常项。', en:'Run command-line inspection and summarize anomalies.'}
      },
      task_fault_diagnosis: {
        label: {zh:'故障诊断', en:'Fault diagnosis'},
        desc: {zh:'从现象、日志和指标定位根因。', en:'Find root causes from symptoms, logs, and metrics.'}
      },
      'host-discovery': {
        label: {zh:'主机发现', en:'Host discovery'},
        desc: {zh:'发现主机、服务、端口和资产归属信息。', en:'Discover hosts, services, ports, and ownership metadata.'}
      },
      neo4j_graph: {
        label: {zh:'关系图谱', en:'Relationship graph'},
        desc: {zh:'生成和查询主机、应用、资产之间的关系。', en:'Build and query relationships between hosts, apps, and assets.'}
      },
      'asset-normalization': {
        label: {zh:'资产规范化', en:'Asset normalization'},
        desc: {zh:'统一资产字段、命名和缺失项。', en:'Normalize asset fields, naming, and missing values.'}
      },
      'zk-ops-iteration-tracker': {
        label: {zh:'迭代追踪', en:'Iteration tracker'},
        desc: {zh:'维护 ZK 运维智能体迭代记录、日报和进展。', en:'Maintain ZK operations iteration records, daily notes, and progress.'}
      },
      'zk-ops-platform-doc': {
        label: {zh:'平台文档', en:'Platform docs'},
        desc: {zh:'整理平台知识、操作手册和文档结构。', en:'Organize platform knowledge, manuals, and document structure.'}
      }
    }
  };

  const COPY = {
    en: {
      title_suffix: 'operations agent',
      agent_default_title: 'Operations agent',
      agents: 'Agent',
      capabilities: 'Skill directories',
      skills: 'Skills',
      cases: 'Practice cases',
      dictionary: 'Dictionary',
      dictionary_title: 'Dictionary management',
      dict_agents: 'Agents',
      dict_categories: 'Directories',
      dict_skills: 'Skills',
      dict_type: 'Type',
      dict_filter_group: 'Filter by type',
      dict_source: 'Source',
      dict_target: 'Chinese label',
      dict_description: 'Chinese description',
      dict_save: 'Save',
      dict_close: 'Close',
      dict_saved: 'Dictionary saved',
      dict_filter_all: 'All',
      dict_filter_search: 'Search dictionary',
      dict_filter_placeholder: 'Search source, label, or description',
      dict_no_matches: 'No matching dictionary entries.',
      rotate: 'Refresh',
      loading: 'Loading...',
      loading_skills: 'Loading skills...',
      loading_cases: 'Loading practice cases...',
      load_failed: 'Unable to load skills right now.',
      no_profiles: 'No profiles available.',
      no_skills: 'No matching skills for this capability.',
      skills_count: '{count} skills',
      disabled: 'Disabled',
      active: 'Active',
      default_profile: 'Default',
      selected_skill_context: 'Use skill: {label}',
      prompt_prefix: 'Please use the "{label}" skill to ',
      capability_prompt_diagnosis: 'diagnose the symptom, likely root cause, and impact surface.',
      capability_prompt_inspection: 'inspect runtime state, key metrics, and anomalies.',
      capability_prompt_asset: 'organize and update the relevant asset information.',
      capability_prompt_report: 'summarize the work and produce a structured operations report.',
      capability_prompt_knowledge: 'distill knowledge points and preserve useful sources.',
      capability_prompt_documents: 'process the document content and extract the key details.'
    },
    zh: {
      title_suffix: '运维智能体',
      agent_default_title: '运维智能体',
      agents: '智能体',
      capabilities: '技能目录',
      skills: '技能',
      cases: '最佳实践案例',
      dictionary: '字典管理',
      dictionary_title: '字典管理',
      dict_agents: '智能体',
      dict_categories: '技能目录',
      dict_skills: '技能',
      dict_type: '类型',
      dict_filter_group: '按类型筛选',
      dict_source: '原文',
      dict_target: '中文名称',
      dict_description: '中文描述',
      dict_save: '保存',
      dict_close: '关闭',
      dict_saved: '字典已保存',
      dict_filter_all: '全部',
      dict_filter_search: '搜索字典',
      dict_filter_placeholder: '搜索原文、中文名称或描述',
      dict_no_matches: '没有匹配的字典项。',
      rotate: '换一批',
      loading: '加载中...',
      loading_skills: '正在加载技能...',
      loading_cases: '正在加载最佳实践案例...',
      load_failed: '暂时无法加载技能。',
      no_profiles: '暂无可用智能体。',
      no_skills: '该能力分类下暂无匹配技能。',
      skills_count: '{count} 个技能',
      disabled: '已停用',
      active: '当前',
      default_profile: '默认',
      selected_skill_context: '使用技能：{label}',
      prompt_prefix: '请使用「{label}」技能，',
      capability_prompt_diagnosis: '定位问题现象、根因和影响面，并给出修复建议。',
      capability_prompt_inspection: '检查运行状态、关键指标和异常，并输出结论。',
      capability_prompt_asset: '梳理并更新相关资产信息，标记缺口和风险。',
      capability_prompt_report: '整理执行结果并输出结构化运维报告。',
      capability_prompt_knowledge: '提炼知识要点、保留来源，并沉淀可复用条目。',
      capability_prompt_documents: '处理文档内容，提取关键信息并整理结构。'
    }
  };

  const CAPABILITIES = [
    {id:'diagnosis', icon:'alert-triangle', label:{zh:'故障诊断', en:'Troubleshooting'}, keywords:['故障','诊断','异常','告警','排查','根因','debug','diagnosis','incident','fault','error','alert']},
    {id:'inspection', icon:'refresh-cw', label:{zh:'日常巡检', en:'Daily inspection'}, keywords:['巡检','巡查','健康','监控','检查','inspection','inspect','health','monitor','check','zabbix','tcms','shell_inspection']},
    {id:'asset', icon:'folder', label:{zh:'资产管理', en:'Asset management'}, keywords:['资产','主机','拓扑','关系','发现','台账','asset','host','graph','neo4j','inventory','discovery','normalization']},
    {id:'report', icon:'clipboard-list', label:{zh:'运维报告生成', en:'Ops reports'}, keywords:['报告','日报','周报','复盘','汇总','迭代','report','summary','iteration','tracker','weekly','daily']},
    {id:'knowledge', icon:'book-open', label:{zh:'知识库管理', en:'Knowledge base'}, keywords:['知识','知识库','手册','平台文档','经验','wiki','knowledge','kb','platform-doc','playbook','notes']},
    {id:'documents', icon:'file-text', label:{zh:'文档处理', en:'Document processing'}, keywords:['文档','文件','表格','材料','document','docx','pdf','office','markdown','word','excel','sheet']}
  ];

  const CAPABILITY_BY_ID = new Map(CAPABILITIES.map(item => [item.id, item]));
  const CATEGORY_ICON_RULES = [
    {icon:'alert-triangle', keywords:['diagnosis','fault','incident','alert','故障','告警']},
    {icon:'refresh-cw', keywords:['inspection','inspect','monitor','devops','operations','运维','巡检','监控']},
    {icon:'folder', keywords:['asset','host','inventory','资产','主机']},
    {icon:'clipboard-list', keywords:['report','summary','iteration','报告','日报','周报']},
    {icon:'book-open', keywords:['knowledge','wiki','memory','知识','文档']},
    {icon:'file-text', keywords:['document','documents','pdf','office','paper','arxiv','文档','论文']},
    {icon:'code', keywords:['code','coding','development','developer','研发','开发']},
    {icon:'check', keywords:['test','tester','testing','测试']},
    {icon:'palette', keywords:['ui','design','designer','设计']},
    {icon:'search', keywords:['research','search','browser','academic','检索','搜索']}
  ];

  const SKILL_OVERRIDES = {
    'shell_inspection_v3': {capability:'inspection', icon:'refresh-cw', priority:100, label:{zh:'巡检 TCMS 程序', en:'Inspect TCMS program'}, desc:{zh:'检查进程、端口、资源占用与关键指标。', en:'Check processes, ports, resource usage, and key metrics.'}},
    'shell_inspection_v2': {capability:'inspection', icon:'refresh-cw', priority:95, label:{zh:'巡检 TCMS 程序', en:'Inspect TCMS program'}, desc:{zh:'执行 Shell 巡检并汇总异常。', en:'Run shell inspection and summarize anomalies.'}},
    'shell_inspection': {capability:'inspection', icon:'refresh-cw', priority:90, label:{zh:'Shell 巡检', en:'Shell inspection'}},
    'task_fault_diagnosis': {capability:'diagnosis', icon:'alert-triangle', priority:100, label:{zh:'故障诊断', en:'Fault diagnosis'}},
    'host-discovery': {capability:'asset', icon:'folder', priority:100, label:{zh:'主机发现', en:'Host discovery'}, desc:{zh:'发现主机、服务、端口和资产归属信息。', en:'Discover hosts, services, ports, and ownership metadata for operations assets.'}},
    'neo4j_graph': {capability:'asset', icon:'share-2', priority:90, label:{zh:'关系图谱', en:'Relationship graph'}},
    'asset-normalization': {capability:'asset', icon:'folder', priority:85, label:{zh:'资产规范化', en:'Asset normalization'}},
    'zk-ops-iteration-tracker': {capability:'report', icon:'clipboard-list', priority:100, label:{zh:'迭代追踪', en:'Iteration tracker'}},
    'zk-ops-platform-doc': {capability:'knowledge', icon:'book-open', priority:100, label:{zh:'平台文档', en:'Platform docs'}}
  };

  const CASE_LIBRARY = [
    {id:'inspection-tcms', capability:'inspection', skillName:'shell_inspection_v3', icon:'refresh-cw', title:{zh:'巡检 TCMS 程序', en:'Inspect TCMS program'}, desc:{zh:'检查运行状态、进程、端口、CPU、内存和磁盘。', en:'Check runtime state, processes, ports, CPU, memory, and disk.'}},
    {id:'inspection-zabbix', capability:'inspection', skillName:'shell_inspection_v3', icon:'refresh-cw', title:{zh:'核查 Zabbix 告警', en:'Review Zabbix alerts'}, desc:{zh:'梳理告警对象、指标波动和处理建议。', en:'Summarize alert targets, metric changes, and actions.'}},
    {id:'inspection-host-health', capability:'inspection', skillName:'host-discovery', icon:'search', title:{zh:'主机健康概览', en:'Host health overview'}, desc:{zh:'收集主机运行状态并标记异常节点。', en:'Collect host status and mark abnormal nodes.'}},
    {id:'inspection-report', capability:'inspection', skillName:'zk-ops-iteration-tracker', icon:'clipboard-list', title:{zh:'生成巡检结论', en:'Generate inspection summary'}, desc:{zh:'将巡检结果整理为结论、风险和下一步。', en:'Turn inspection output into findings, risks, and next steps.'}},
    {id:'inspection-service', capability:'inspection', skillName:'shell_inspection_v3', icon:'refresh-cw', title:{zh:'检查关键服务', en:'Check critical services'}, desc:{zh:'确认服务进程、端口和依赖是否稳定。', en:'Validate service processes, ports, and dependencies.'}},
    {id:'inspection-baseline', capability:'inspection', skillName:'shell_inspection_v2', icon:'refresh-cw', title:{zh:'建立巡检基线', en:'Create an inspection baseline'}, desc:{zh:'沉淀常用指标、阈值和异常判断。', en:'Capture metrics, thresholds, and anomaly rules.'}},

    {id:'diagnosis-alert-root', capability:'diagnosis', skillName:'task_fault_diagnosis', icon:'alert-triangle', title:{zh:'定位告警根因', en:'Find alert root cause'}, desc:{zh:'从现象、日志和指标推断最可能根因。', en:'Use symptoms, logs, and metrics to find the root cause.'}},
    {id:'diagnosis-deploy', capability:'diagnosis', skillName:'task_fault_diagnosis', icon:'search', title:{zh:'排查部署失败', en:'Debug deployment failure'}, desc:{zh:'串联发布日志、服务状态和回滚建议。', en:'Link deployment logs, service state, and rollback actions.'}},
    {id:'diagnosis-slow', capability:'diagnosis', skillName:'task_fault_diagnosis', icon:'cpu', title:{zh:'分析性能异常', en:'Analyze performance anomaly'}, desc:{zh:'定位慢请求、资源压力和影响范围。', en:'Identify slow requests, pressure points, and impact.'}},
    {id:'diagnosis-runbook', capability:'diagnosis', skillName:'zk-ops-platform-doc', icon:'book-open', title:{zh:'沉淀排障步骤', en:'Capture a runbook'}, desc:{zh:'把一次排障过程整理成可复用流程。', en:'Turn an investigation into a reusable runbook.'}},
    {id:'diagnosis-log', capability:'diagnosis', skillName:'task_fault_diagnosis', icon:'file-text', title:{zh:'解读异常日志', en:'Interpret error logs'}, desc:{zh:'提炼关键堆栈、时间线和修复方向。', en:'Extract key stacks, timeline, and repair direction.'}},
    {id:'diagnosis-risk', capability:'diagnosis', skillName:'task_fault_diagnosis', icon:'alert-triangle', title:{zh:'评估影响面', en:'Assess impact'}, desc:{zh:'明确用户、系统和数据层面的影响。', en:'Clarify user, system, and data impact.'}},

    {id:'asset-inventory', capability:'asset', skillName:'host-discovery', icon:'clipboard-list', title:{zh:'资产自动盘点', en:'Automated asset inventory'}, desc:{zh:'定期扫描全量主机、服务与端口，自动生成资产拓扑与风险清单。', en:'Scan hosts, services, and ports on a schedule, then produce topology and risk lists.'}},
    {id:'asset-compliance', capability:'asset', skillName:'asset-normalization', icon:'check', title:{zh:'合规基线检查', en:'Compliance baseline check'}, desc:{zh:'依据安全基线对主机配置进行巡检，快速定位不合规项并推送修复建议。', en:'Check host configuration against security baselines and recommend fixes.'}},
    {id:'asset-graph', capability:'asset', skillName:'neo4j_graph', icon:'share-2', title:{zh:'生成资产关系图', en:'Build asset graph'}, desc:{zh:'梳理主机、应用、依赖和上下游关系。', en:'Map hosts, apps, dependencies, and upstream/downstream links.'}},
    {id:'asset-gap', capability:'asset', skillName:'asset-normalization', icon:'search', title:{zh:'盘点资产缺口', en:'Find inventory gaps'}, desc:{zh:'标记缺字段、重复项和疑似失效资产。', en:'Flag missing fields, duplicates, and stale assets.'}},
    {id:'asset-owner', capability:'asset', skillName:'asset-normalization', icon:'user', title:{zh:'梳理资产责任人', en:'Clarify asset owners'}, desc:{zh:'按系统和环境整理负责人和交接信息。', en:'Organize owners and handoff notes by system and environment.'}},
    {id:'asset-change', capability:'asset', skillName:'host-discovery', icon:'refresh-cw', title:{zh:'核对资产变更', en:'Review asset changes'}, desc:{zh:'比较当前资产与上次基线的差异。', en:'Compare current inventory against the last baseline.'}},

    {id:'report-daily', capability:'report', skillName:'zk-ops-iteration-tracker', icon:'clipboard-list', title:{zh:'生成运维日报', en:'Generate daily ops report'}, desc:{zh:'汇总巡检、告警、变更和待办事项。', en:'Summarize inspections, alerts, changes, and follow-ups.'}},
    {id:'report-weekly', capability:'report', skillName:'zk-ops-iteration-tracker', icon:'calendar', title:{zh:'整理运维周报', en:'Prepare weekly ops report'}, desc:{zh:'按系统、风险、进度和行动项输出周报。', en:'Report by system, risk, progress, and actions.'}},
    {id:'report-incident', capability:'report', skillName:'task_fault_diagnosis', icon:'file-text', title:{zh:'输出故障复盘', en:'Write incident review'}, desc:{zh:'整理时间线、根因、影响和改进项。', en:'Capture timeline, root cause, impact, and improvements.'}},
    {id:'report-change', capability:'report', skillName:'zk-ops-iteration-tracker', icon:'clipboard-list', title:{zh:'汇总迭代事项', en:'Summarize iteration items'}, desc:{zh:'把任务进展、阻塞和下一步整理清楚。', en:'Clarify progress, blockers, and next steps.'}},
    {id:'report-risk', capability:'report', skillName:'zk-ops-iteration-tracker', icon:'alert-triangle', title:{zh:'生成风险清单', en:'Create risk list'}, desc:{zh:'提炼风险等级、影响范围和处理建议。', en:'Extract severity, impact, and recommended actions.'}},
    {id:'report-handoff', capability:'report', skillName:'zk-ops-iteration-tracker', icon:'share-2', title:{zh:'整理交接摘要', en:'Prepare handoff summary'}, desc:{zh:'汇总当前状态、遗留问题和负责事项。', en:'Summarize status, open issues, and ownership.'}},

    {id:'knowledge-platform', capability:'knowledge', skillName:'zk-ops-platform-doc', icon:'book-open', title:{zh:'更新平台文档', en:'Update platform docs'}, desc:{zh:'补齐背景、步骤、注意事项和验证方法。', en:'Add context, steps, cautions, and validation.'}},
    {id:'knowledge-runbook', capability:'knowledge', skillName:'zk-ops-platform-doc', icon:'book-open', title:{zh:'沉淀操作手册', en:'Capture an operations manual'}, desc:{zh:'将重复操作整理成可执行清单。', en:'Turn repeated work into an executable checklist.'}},
    {id:'knowledge-faq', capability:'knowledge', skillName:'zk-ops-platform-doc', icon:'file-text', title:{zh:'整理知识库 FAQ', en:'Organize FAQ'}, desc:{zh:'归纳常见问题、答案和来源。', en:'Group common questions, answers, and sources.'}},
    {id:'knowledge-experience', capability:'knowledge', skillName:'task_fault_diagnosis', icon:'book-open', title:{zh:'沉淀排障经验', en:'Capture troubleshooting notes'}, desc:{zh:'把现场经验转成可检索知识条目。', en:'Convert field experience into searchable knowledge.'}},
    {id:'knowledge-review', capability:'knowledge', skillName:'zk-ops-platform-doc', icon:'search', title:{zh:'复核知识条目', en:'Review knowledge entries'}, desc:{zh:'检查过期信息、缺失步骤和责任人。', en:'Check stale facts, missing steps, and owners.'}},
    {id:'knowledge-index', capability:'knowledge', skillName:'neo4j_graph', icon:'share-2', title:{zh:'建立知识关系', en:'Map knowledge relationships'}, desc:{zh:'连接系统、故障、资产和文档之间的关系。', en:'Connect systems, issues, assets, and documents.'}},

    {id:'documents-structure', capability:'documents', skillName:'zk-ops-platform-doc', icon:'file-text', title:{zh:'整理文档结构', en:'Structure documents'}, desc:{zh:'提取标题、步骤、字段和待确认项。', en:'Extract headings, steps, fields, and open questions.'}},
    {id:'documents-checklist', capability:'documents', skillName:'zk-ops-platform-doc', icon:'clipboard-list', title:{zh:'转换操作清单', en:'Convert to checklist'}, desc:{zh:'把长文档转成可执行检查项。', en:'Turn long-form docs into executable checks.'}},
    {id:'documents-summary', capability:'documents', skillName:'zk-ops-platform-doc', icon:'file-text', title:{zh:'提炼文档摘要', en:'Summarize documents'}, desc:{zh:'保留关键事实、来源和后续动作。', en:'Keep key facts, sources, and next actions.'}},
    {id:'documents-gap', capability:'documents', skillName:'zk-ops-platform-doc', icon:'search', title:{zh:'发现文档缺口', en:'Find document gaps'}, desc:{zh:'标记缺少前置条件、验证和失败处理。', en:'Flag missing prerequisites, validation, and failure handling.'}},
    {id:'documents-fields', capability:'documents', skillName:'asset-normalization', icon:'hash', title:{zh:'抽取表格字段', en:'Extract table fields'}, desc:{zh:'从材料中整理字段、含义和规范。', en:'Extract fields, meanings, and standards.'}},
    {id:'documents-merge', capability:'documents', skillName:'zk-ops-platform-doc', icon:'layers', title:{zh:'合并多份材料', en:'Merge multiple documents'}, desc:{zh:'去重冲突内容并输出统一版本。', en:'Deduplicate conflicts and produce one version.'}}
  ];

  const state = {
    profiles: [],
    profilesLoading: false,
    profilesError: false,
    activeProfile: '',
    singleProfileMode: false,
    profileRequestId: 0,
    skills: [],
    skillsLoading: false,
    skillsError: false,
    skillsRequestId: 0,
    selectedCapability: readStoredCapability(),
    selectedSkillName: '',
    selectedCaseId: '',
    caseBatchIndex: readStoredCaseBatch(),
    initializing: true,
    switchingProfile: false,
    autoSwitchAttempted: false,
    postBootAutoSwitchScheduled: false,
    lastLaunchPrompt: ''
  };

  let bootPromise = null;
  let profilePromise = null;
  let skillPromise = null;
  let customGuideTranslations = readStoredGuideDictionary();

  function isZh(){
    const lang = String((window._locale && window._locale._speech) || document.documentElement.lang || '').toLowerCase();
    return lang.startsWith('zh') || (!lang && navigator.language && String(navigator.language).toLowerCase().startsWith('zh'));
  }

  function copy(){ return isZh() ? COPY.zh : COPY.en; }

  function t(key){
    const bag = copy();
    return bag[key] || COPY.en[key] || key;
  }

  function readStoredGuideDictionary(){
    try{
      const raw = localStorage.getItem(STORAGE_DICTIONARY);
      if(!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    }catch(_){ return {}; }
  }

  function writeStoredGuideDictionary(){
    try{ localStorage.setItem(STORAGE_DICTIONARY, JSON.stringify(customGuideTranslations || {})); }catch(_){ }
  }

  function mergeTranslationEntry(base, custom){
    if(!custom || typeof custom !== 'object') return base || null;
    if(!base || typeof base !== 'object') return custom;
    return {
      ...base,
      ...custom,
      label: {...(base.label || {}), ...(custom.label || {})},
      desc: {...(base.desc || {}), ...(custom.desc || {})}
    };
  }

  function dictionaryEntry(section, key){
    const normalizedKey = String(key || '').trim();
    const base = (GUIDE_TRANSLATION_DICTIONARY[section] || {})[normalizedKey] || null;
    const custom = (customGuideTranslations[section] || {})[normalizedKey] || null;
    return mergeTranslationEntry(base, custom);
  }

  function localize(value, fallback){
    if(value && typeof value === 'object'){
      const preferred = isZh() ? value.zh : value.en;
      const backup = isZh() ? value.en : value.zh;
      if(typeof preferred === 'string' && preferred.trim()) return preferred;
      if(typeof backup === 'string' && backup.trim()) return backup;
    }
    if(typeof value === 'string' && value.trim()) return value;
    return fallback || '';
  }

  function translateGuideEntry(section, key, fallback){
    const entry = dictionaryEntry(section, key);
    if(entry) return localize(entry, fallback);
    return fallback || '';
  }

  function normalizeDictionaryKey(value){
    return String(value || '').trim().toLowerCase();
  }

  function translateAgentName(name, fallback){
    const raw = normalizeDictionaryKey(name);
    const compact = raw.replace(/[_\s]+/g, '-');
    const normalized = raw.replace(/[_\s-]+/g, '');
    const direct = dictionaryEntry('agents', raw) || dictionaryEntry('agents', compact) || dictionaryEntry('agents', normalized);
    if(direct) return localize(direct, fallback);
    if((name || '').includes('查询') || normalized.includes('query') || normalized.includes('search') || normalized.includes('chaxun')){
      return localize(dictionaryEntry('agents', 'query'), fallback);
    }
    if((name || '').includes('数匠') || normalized.includes('shuj') || normalized.includes('data')){
      return localize(dictionaryEntry('agents', 'data'), fallback);
    }
    return fallback || name || '';
  }

  function skillDisplayText(name, field, fallback){
    const entry = dictionaryEntry('skills', name);
    if(entry && entry[field]) return localize(entry[field], fallback);
    return fallback || '';
  }

  function escapeHtml(value){
    if(typeof esc === 'function') return esc(value);
    return String(value == null ? '' : value).replace(/[&<>"']/g, char => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    }[char]));
  }

  function icon(name, size){
    return typeof li === 'function' ? li(name, size || 16) : '';
  }

  function root(){ return document.getElementById('emptyState'); }
  function guide(){ return document.getElementById('sessionGuide'); }
  function byId(id){ return document.getElementById(id); }

  function syncShellScrollState(){
    const rootElement = root();
    const messages = byId('messages');
    if(!messages || !rootElement) return;
    const active = rootElement.style.display !== 'none' &&
      rootElement.classList.contains('session-guide-active') &&
      !rootElement.classList.contains('workspace-empty-state') &&
      !!guide();
    messages.classList.toggle('session-guide-shell-active', active);
  }

  function readStoredCapability(){
    try{
      const value = String(localStorage.getItem(STORAGE_CAPABILITY) || '').trim();
      return value || DEFAULT_CAPABILITY;
    }catch(_){ return DEFAULT_CAPABILITY; }
  }

  function storeCapability(value){
    try{ localStorage.setItem(STORAGE_CAPABILITY, value); }catch(_){ }
  }

  function readStoredCaseBatch(){
    try{
      const value = Number(localStorage.getItem(STORAGE_CASE_BATCH));
      return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
    }catch(_){ return 0; }
  }

  function storeCaseBatch(value){
    try{ localStorage.setItem(STORAGE_CASE_BATCH, String(value)); }catch(_){ }
  }

  function currentActiveProfileName(){
    const fromApi = String(state.activeProfile || '').trim();
    if(fromApi) return fromApi;
    const fromState = (typeof S !== 'undefined' && S && S.activeProfile) ? S.activeProfile : '';
    const active = String(fromState || '').trim();
    return active || 'default';
  }

  function activeProfileLabel(){
    const active = currentActiveProfileName();
    if(active && active !== 'default') return active;
    return DEFAULT_AGENT;
  }

  function agentDisplayLabel(profile){
    const name = String(profile && profile.name || profile || '').trim() || 'default';
    return translateAgentName(name, name);
  }

  function renderCopy(){
    const setText = (id, value) => {
      const element = byId(id);
      if(element) element.textContent = value;
    };
    setText('sessionGuideAgentsTitle', t('agents'));
    setText('sessionGuideCapabilitiesTitle', t('capabilities'));
    setText('sessionGuideSkillsTitle', t('skills'));
    setText('sessionGuideCasesTitle', t('cases'));
    const mark = byId('sessionGuideMark');
    if(mark) mark.innerHTML = icon('sparkles', 28);
    const rotate = byId('sessionGuideRotateCases');
    if(rotate){
      rotate.innerHTML = `<span class="session-guide-reroll-icon">${icon('shuffle', 14)}</span><span>${escapeHtml(t('rotate'))}</span>`;
      rotate.setAttribute('aria-label', t('rotate'));
      rotate.title = t('rotate');
    }
    const agentList = byId('sessionGuideAgents');
    if(agentList) agentList.setAttribute('aria-label', t('agents'));
    const capabilityList = byId('sessionGuideCapabilities');
    if(capabilityList) capabilityList.setAttribute('aria-label', t('capabilities'));
    const dictionaryBtn = byId('sessionGuideDictionaryBtn');
    if(dictionaryBtn){
      dictionaryBtn.innerHTML = `${icon('languages', 14)}<span>${escapeHtml(t('dictionary'))}</span>`;
      dictionaryBtn.setAttribute('aria-label', t('dictionary_title'));
      dictionaryBtn.title = t('dictionary_title');
    }
  }

  function renderTitle(){
    const title = byId('sessionGuideTitle');
    if(!title) return;
    title.textContent = t('agent_default_title');
  }

  function normalizeProfileRows(rows){
    const source = Array.isArray(rows) ? rows : [];
    const visible = source.filter(p => p && typeof p.name === 'string' && p.name.trim() && p.visible !== false);
    const list = visible.length ? visible : source.filter(p => p && typeof p.name === 'string' && p.name.trim());
    if(list.length) return list;
    return [{name:currentActiveProfileName(), is_active:true, is_default:true, visible:true}];
  }

  function sortedProfiles(){
    const active = currentActiveProfileName();
    return normalizeProfileRows(state.profiles).slice().sort((a, b) => {
      if(a.name === active && b.name !== active) return -1;
      if(b.name === active && a.name !== active) return 1;
      if(a.name === DEFAULT_AGENT && b.name !== DEFAULT_AGENT) return -1;
      if(b.name === DEFAULT_AGENT && a.name !== DEFAULT_AGENT) return 1;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
  }

  function profileMeta(profile, selected){
    const bits = [];
    if(selected) bits.push(t('active'));
    if(profile && profile.is_default) bits.push(t('default_profile'));
    return bits.join(' / ');
  }

  function renderAgents(){
    const container = byId('sessionGuideAgents');
    if(!container) return;
    if(state.profilesLoading && !state.profiles.length){
      container.innerHTML = `<button type="button" class="session-guide-chip" disabled><span class="session-guide-chip-icon">${icon('loader', 14)}</span><span class="session-guide-chip-title">${escapeHtml(t('loading'))}</span></button>`;
      return;
    }
    if(state.profilesError && !state.profiles.length){
      container.innerHTML = `<div class="session-guide-skill-empty">${escapeHtml(t('no_profiles'))}</div>`;
      return;
    }
    const active = currentActiveProfileName();
    const profiles = sortedProfiles();
    container.innerHTML = profiles.map(profile => {
      const name = String(profile.name || 'default');
      const selected = name === active || (!state.profiles.some(p => p.name === active) && profile.is_default);
      const disabled = state.singleProfileMode || state.switchingProfile;
      const agentIcon = state.switchingProfile && selected ? 'loader' : 'bot';
      const meta = profileMeta(profile, selected);
      const label = agentDisplayLabel(profile);
      const title = meta ? `${name} / ${meta}` : name;
      return `<button type="button" class="session-guide-chip session-guide-agent-chip" data-session-guide-agent="${escapeHtml(name)}" aria-pressed="${selected ? 'true' : 'false'}" ${disabled ? 'disabled' : ''} title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">
        <span class="session-guide-chip-icon">${icon(agentIcon, 15)}</span>
        <span class="session-guide-chip-body">
          <span class="session-guide-chip-title">${escapeHtml(label)}</span>
        </span>
      </button>`;
    }).join('');
  }

  function scoreCapabilityText(text, capability){
    const hay = String(text || '').toLowerCase();
    return (capability.keywords || []).reduce((score, keyword) => {
      const token = String(keyword || '').toLowerCase();
      return token && hay.includes(token) ? score + 1 : score;
    }, 0);
  }

  function skillOverride(skill){
    const name = String(skill && skill.name || '');
    return SKILL_OVERRIDES[name] || null;
  }

  function inferCapability(skill){
    const override = skillOverride(skill);
    if(override && override.capability) return override.capability;
    const text = [skill && skill.name, skill && skill.category, skill && skill.description].filter(Boolean).join(' ');
    let best = DEFAULT_CAPABILITY;
    let bestScore = 0;
    CAPABILITIES.forEach(capability => {
      const score = scoreCapabilityText(text, capability);
      if(score > bestScore){
        best = capability.id;
        bestScore = score;
      }
    });
    return bestScore > 0 ? best : '';
  }

  function skillDirectory(skill){
    const category = String(skill && skill.category || '').trim();
    return category || '(general)';
  }

  function prettifyDictionaryKey(key){
    const raw = String(key || '').trim();
    if(!raw || raw === '(general)') return isZh() ? '通用' : 'General';
    const spaced = raw.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
    return spaced.replace(/\b\w/g, ch => ch.toUpperCase());
  }

  function directoryIcon(id){
    const known = CAPABILITY_BY_ID.get(id);
    if(known && known.icon) return known.icon;
    const text = String(id || '').toLowerCase();
    const match = CATEGORY_ICON_RULES.find(rule => (rule.keywords || []).some(keyword => text.includes(String(keyword).toLowerCase())));
    return match ? match.icon : 'folder';
  }

  function catalogCapabilities(){
    const categories = [];
    const seen = new Set();
    (state.skills || []).forEach(skill => {
      const id = skillDirectory(skill);
      if(!id || seen.has(id)) return;
      seen.add(id);
      categories.push(id);
    });
    if(!categories.length) return CAPABILITIES;
    return categories.sort((a, b) => {
      if(a === DEFAULT_CAPABILITY && b !== DEFAULT_CAPABILITY) return -1;
      if(b === DEFAULT_CAPABILITY && a !== DEFAULT_CAPABILITY) return 1;
      return translateGuideEntry('capabilities', a, prettifyDictionaryKey(a)).localeCompare(
        translateGuideEntry('capabilities', b, prettifyDictionaryKey(b))
      );
    }).map(id => ({
      id,
      icon: directoryIcon(id),
      label: translateGuideEntry('capabilities', id, prettifyDictionaryKey(id)),
      keywords: [id]
    }));
  }

  function capabilityFor(id){
    return catalogCapabilities().find(item => item.id === id)
      || CAPABILITY_BY_ID.get(id)
      || CAPABILITY_BY_ID.get(DEFAULT_CAPABILITY)
      || CAPABILITIES[0];
  }

  function normalizedSkills(){
    const seen = new Set();
    return (state.skills || []).filter(skill => {
      const name = String(skill && skill.name || '').trim();
      if(!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    }).map(skill => {
      const override = skillOverride(skill) || {};
      const directory = skillDirectory(skill);
      const capability = directory || override.capability || inferCapability(skill) || '';
      const fallbackLabel = localize(override.label, String(skill.name || ''));
      const fallbackDesc = localize(override.desc, compactText(skill.description || '', 88));
      const label = skillDisplayText(skill.name, 'label', fallbackLabel);
      const desc = skillDisplayText(skill.name, 'desc', fallbackDesc);
      return {
        raw: skill,
        name: String(skill.name || ''),
        disabled: skill.disabled === true,
        label,
        desc,
        icon: override.icon || directoryIcon(capability) || 'sparkles',
        capability,
        intentCapability: override.capability || inferCapability(skill) || capability,
        priority: Number(override.priority || 0)
      };
    });
  }

  function caseSkillNamesForCapability(capabilityId){
    return new Set(CASE_LIBRARY
      .filter(item => item.capability === capabilityId && item.skillName)
      .map(item => item.skillName));
  }

  function skillsMatchingCapability(capabilityId){
    const all = normalizedSkills();
    const direct = all.filter(skill => skill.capability === capabilityId);
    if(direct.length || state.skills.length) return direct;
    const caseSkillNames = caseSkillNamesForCapability(capabilityId);
    return all.filter(skill => caseSkillNames.has(skill.name));
  }

  function skillsForCapability(capabilityId){
    return skillsMatchingCapability(capabilityId).sort((a, b) => {
      if(a.disabled !== b.disabled) return a.disabled ? 1 : -1;
      if(a.priority !== b.priority) return b.priority - a.priority;
      return a.label.localeCompare(b.label);
    });
  }

  function capabilityHasSkills(capabilityId){
    return skillsMatchingCapability(capabilityId).length > 0;
  }

  function normalizeSelectedCapability(){
    const capabilities = catalogCapabilities();
    if(capabilities.some(capability => capability.id === state.selectedCapability)){
      if(!state.skills.length || capabilityHasSkills(state.selectedCapability)) return state.selectedCapability;
    }
    const firstWithSkills = capabilities.find(capability => capabilityHasSkills(capability.id));
    const next = firstWithSkills ? firstWithSkills.id : ((capabilities[0] && capabilities[0].id) || DEFAULT_CAPABILITY);
    if(state.selectedCapability !== next){
      state.selectedCapability = next;
      storeCapability(next);
    }
    return next;
  }

  function renderCapabilities(){
    const container = byId('sessionGuideCapabilities');
    if(!container) return;
    if((state.initializing || state.skillsLoading) && !state.skills.length){
      container.innerHTML = `<button type="button" class="session-guide-chip session-guide-capability-chip" disabled><span class="session-guide-chip-icon">${icon('loader', 14)}</span><span class="session-guide-chip-title">${escapeHtml(t('loading_skills'))}</span></button>`;
      return;
    }
    const selected = normalizeSelectedCapability();
    container.innerHTML = catalogCapabilities().map(capability => {
      const active = capability.id === selected;
      const label = translateGuideEntry('capabilities', capability.id, localize(capability.label, prettifyDictionaryKey(capability.id)));
      return `<button type="button" class="session-guide-chip session-guide-capability-chip" data-session-guide-capability="${escapeHtml(capability.id)}" aria-pressed="${active ? 'true' : 'false'}">
        <span class="session-guide-chip-icon">${icon(capability.icon, 15)}</span>
        <span class="session-guide-chip-title">${escapeHtml(label)}</span>
      </button>`;
    }).join('');
  }

  function compactText(value, max){
    const normalized = String(value || '').replace(/\s+/g, ' ').trim();
    if(!normalized) return '';
    const limit = Number(max) || 96;
    return normalized.length > limit ? normalized.slice(0, limit).trimEnd() + '...' : normalized;
  }

  function renderSkills(){
    const container = byId('sessionGuideSkillList');
    const count = byId('sessionGuideSkillCount');
    if(!container) return;
    if((state.initializing || state.skillsLoading) && !state.skills.length){
      if(count) count.textContent = '';
      container.innerHTML = `<div class="session-guide-skill-loading">${icon('loader', 14)}<span>${escapeHtml(t('loading_skills'))}</span></div>`;
      return;
    }
    if(state.skillsError){
      if(count) count.textContent = '';
      container.innerHTML = `<div class="session-guide-skill-empty">${escapeHtml(t('load_failed'))}</div>`;
      return;
    }
    const selected = normalizeSelectedCapability();
    const visible = skillsForCapability(selected);
    if(count) count.textContent = t('skills_count').replace('{count}', String(visible.length));
    if(!visible.length){
      container.innerHTML = `<div class="session-guide-skill-empty">${escapeHtml(t('no_skills'))}</div>`;
      return;
    }
    container.innerHTML = visible.map((skill, index) => {
      const selectedSkill = skill.name && skill.name === state.selectedSkillName;
      const featured = !state.selectedSkillName && index === 0;
      const disabled = skill.disabled;
      const description = skill.desc || compactText(skill.raw && skill.raw.description || '', 88);
      return `<button type="button" class="session-guide-skill-card${selectedSkill ? ' is-selected' : ''}${featured ? ' is-featured' : ''}" data-session-guide-skill="${escapeHtml(skill.name)}" ${disabled ? 'disabled' : ''} aria-pressed="${selectedSkill ? 'true' : 'false'}" title="${escapeHtml(skill.name)}">
        <span class="session-guide-skill-card-head">
          <span class="session-guide-skill-icon">${icon(skill.icon || 'sparkles', 15)}</span>
          <span class="session-guide-skill-copy">
            <span class="session-guide-skill-name">${escapeHtml(skill.label)}</span>
            ${description ? `<span class="session-guide-skill-desc">${escapeHtml(description)}</span>` : ''}
          </span>
          <span class="session-guide-card-arrow">${icon('arrow-right', 14)}</span>
        </span>
        ${disabled ? `<span class="session-guide-skill-state">${escapeHtml(t('disabled'))}</span>` : ''}
      </button>`;
    }).join('');
  }

  function casesForCapability(capabilityId){
    const skillCases = normalizedSkills()
      .filter(skill => skill.capability === capabilityId)
      .map(skill => ({
        id: `skill-case-${skill.name}`,
        capability: capabilityId,
        skillName: skill.name,
        icon: skill.icon,
        title: {zh: skill.label, en: skill.label},
        desc: {zh: skill.desc || '', en: skill.desc || ''}
      }));
    const all = skillCases.length ? skillCases : CASE_LIBRARY.filter(item => item.capability === capabilityId);
    const fallback = all.length ? all : CASE_LIBRARY.slice(0, CASE_BATCH_SIZE);
    const start = (state.caseBatchIndex * CASE_BATCH_SIZE) % fallback.length;
    const rotated = fallback.slice(start).concat(fallback.slice(0, start));
    return rotated.slice(0, Math.min(CASE_BATCH_SIZE, fallback.length));
  }

  function renderCases(){
    const container = byId('sessionGuideCases');
    if(!container) return;
    if((state.initializing || state.skillsLoading) && !state.skills.length){
      container.innerHTML = `<div class="session-guide-case-empty">${icon('loader', 14)}<span>${escapeHtml(t('loading_cases'))}</span></div>`;
      return;
    }
    const selected = normalizeSelectedCapability();
    const cases = casesForCapability(selected);
    if(!cases.length){
      container.innerHTML = `<div class="session-guide-case-empty">${escapeHtml(t('no_skills'))}</div>`;
      return;
    }
    container.innerHTML = cases.map(item => {
      const capability = capabilityFor(item.capability);
      const title = localize(item.title, item.id);
      const desc = localize(item.desc, '');
      const selectedCase = item.id === state.selectedCaseId;
      return `<button type="button" class="session-guide-case-card${selectedCase ? ' is-selected' : ''}" data-session-guide-case="${escapeHtml(item.id)}" aria-pressed="${selectedCase ? 'true' : 'false'}">
        <span class="session-guide-case-icon">${icon(item.icon || capability.icon, 24)}</span>
        <span class="session-guide-case-body">
          <span class="session-guide-case-title">${escapeHtml(title)}</span>
          ${desc ? `<span class="session-guide-case-desc">${escapeHtml(desc)}</span>` : ''}
        </span>
      </button>`;
    }).join('');
  }

  function render(){
    const rootElement = root();
    syncShellScrollState();
    if(!rootElement || rootElement.classList.contains('workspace-empty-state') || !guide()) return;
    rootElement.classList.add('session-guide-active');
    syncShellScrollState();
    renderCopy();
    renderTitle();
    renderAgents();
    renderCapabilities();
    renderSkills();
    renderCases();
  }

  async function loadProfiles(force){
    if(profilePromise && !force) return profilePromise;
    const requestId = ++state.profileRequestId;
    state.profilesLoading = true;
    state.profilesError = false;
    render();
    profilePromise = (async()=>{
      try{
        const data = await api('/api/profiles', {timeoutToast:false});
        if(requestId !== state.profileRequestId) return state.profiles;
        state.profiles = Array.isArray(data && data.profiles) ? data.profiles : [];
        state.activeProfile = String(data && data.active || currentActiveProfileName() || 'default');
        state.singleProfileMode = data && data.single_profile_mode === true;
      }catch(_){
        if(requestId === state.profileRequestId){
          state.profiles = [];
          state.profilesError = true;
        }
      }finally{
        if(requestId === state.profileRequestId){
          state.profilesLoading = false;
          profilePromise = null;
          render();
        }
      }
      return state.profiles;
    })();
    return profilePromise;
  }

  async function loadSkills(force){
    if(skillPromise && !force) return skillPromise;
    const requestId = ++state.skillsRequestId;
    state.skillsLoading = true;
    state.skillsError = false;
    render();
    skillPromise = (async()=>{
      try{
        const data = await api('/api/skills', {timeoutToast:false});
        if(requestId !== state.skillsRequestId) return state.skills;
        state.skills = Array.isArray(data && data.skills) ? data.skills : [];
      }catch(_){
        if(requestId === state.skillsRequestId){
          state.skills = [];
          state.skillsError = true;
        }
      }finally{
        if(requestId === state.skillsRequestId){
          state.skillsLoading = false;
          skillPromise = null;
          render();
        }
      }
      return state.skills;
    })();
    return skillPromise;
  }

  function shouldAutoSwitchToZk(){
    if(state.autoSwitchAttempted || state.singleProfileMode) return false;
    const hasZk = normalizeProfileRows(state.profiles).some(profile => profile.name === DEFAULT_AGENT);
    if(!hasZk) return false;
    const active = currentActiveProfileName();
    const sActive = (typeof S !== 'undefined' && S && S.activeProfile) ? String(S.activeProfile || '').trim() : '';
    const activeIsDefault = active === 'default' || (active === sActive && typeof S !== 'undefined' && S && S.activeProfileIsDefault === true);
    return activeIsDefault && active !== DEFAULT_AGENT;
  }

  function bootReadyForProfileSwitch(){
    return typeof S !== 'undefined' && S && S._bootReady === true;
  }

  async function maybeAutoSwitchToZk(){
    if(!shouldAutoSwitchToZk()) return false;
    if(!bootReadyForProfileSwitch()) return false;
    state.autoSwitchAttempted = true;
    await selectAgent(DEFAULT_AGENT, {auto:true});
    await loadSkills(true).catch(()=>{});
    return true;
  }

  function schedulePostBootAutoSwitch(){
    if(state.postBootAutoSwitchScheduled) return;
    state.postBootAutoSwitchScheduled = true;
    let attempts = 0;
    const run = () => {
      if(!root() || root().classList.contains('workspace-empty-state') || !guide()) return;
      if(!shouldAutoSwitchToZk()) return;
      if(!bootReadyForProfileSwitch()){
        attempts += 1;
        if(attempts < 8) setTimeout(run, 400);
        return;
      }
      void maybeAutoSwitchToZk();
    };
    window.addEventListener('hermes:session-list-ready', run, {once:true});
    setTimeout(run, 1200);
  }

  async function bootstrap(){
    if(bootPromise) return bootPromise;
    state.initializing = true;
    render();
    bootPromise = (async()=>{
      const profiles = loadProfiles();
      const skills = loadSkills();
      await profiles;
      if(shouldAutoSwitchToZk()){
        if(await maybeAutoSwitchToZk()) return true;
        schedulePostBootAutoSwitch();
      }
      await skills;
      return true;
    })().finally(()=>{
      state.initializing = false;
      bootPromise = null;
      render();
    });
    return bootPromise;
  }

  function resetLaunchpadSelection(){
    state.selectedSkillName = '';
    state.selectedCaseId = '';
    if(typeof window._clearPendingSelections === 'function') window._clearPendingSelections();
  }

  function setCapability(id){
    if(!catalogCapabilities().some(capability => capability.id === id) || id === state.selectedCapability) return;
    state.selectedCapability = id;
    state.caseBatchIndex = 0;
    storeCapability(id);
    storeCaseBatch(0);
    resetLaunchpadSelection();
    render();
  }

  async function selectAgent(name, opts){
    const target = String(name || '').trim();
    if(!target || state.switchingProfile) return;
    if(target === currentActiveProfileName()) return;
    if(typeof switchToProfile !== 'function') return;
    resetLaunchpadSelection();
    state.switchingProfile = true;
    render();
    try{
      await switchToProfile(target === DEFAULT_AGENT ? 'zk' : target);
    }finally{
      state.switchingProfile = false;
      if(!(opts && opts.auto)) await loadProfiles(true).catch(()=>{});
      render();
    }
  }

  function buildSkillPrompt(skill){
    const capabilityId = skill.intentCapability || skill.capability || state.selectedCapability || DEFAULT_CAPABILITY;
    const promptKey = `capability_prompt_${capabilityId}`;
    const bag = copy();
    const suffix = bag[promptKey] || COPY.en[promptKey] || bag.capability_prompt_inspection || COPY.en.capability_prompt_inspection;
    return t('prompt_prefix').replace('{label}', skill.label) + suffix;
  }

  function buildSelectionText(label){
    return t('selected_skill_context').replace('{label}', label);
  }

  function setComposerText(prompt){
    const input = typeof $ === 'function' ? $('msg') : byId('msg');
    if(!input) return;
    const current = String(input.value || '');
    const currentTrimmed = current.trim();
    const lastTrimmed = String(state.lastLaunchPrompt || '').trim();
    const shouldReplace = !currentTrimmed || (lastTrimmed && currentTrimmed === lastTrimmed);
    if(shouldReplace){
      input.value = prompt;
      state.lastLaunchPrompt = prompt;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      if(typeof autoResize === 'function') autoResize();
    }
    input.focus();
    try{ input.setSelectionRange(input.value.length, input.value.length); }catch(_){ }
  }

  function applyComposerSelection(label, prompt){
    if(typeof window._clearPendingSelections === 'function') window._clearPendingSelections();
    if(typeof window._addNamedContextBlock === 'function'){
      window._addNamedContextBlock(buildSelectionText(label), label);
    }
    setComposerText(prompt);
  }

  function selectSkillByName(name){
    const skill = normalizedSkills().find(item => item.name === name);
    if(!skill || skill.disabled) return;
    state.selectedCapability = skill.capability || state.selectedCapability;
    storeCapability(state.selectedCapability);
    state.selectedSkillName = skill.name;
    state.selectedCaseId = '';
    applyComposerSelection(skill.label, buildSkillPrompt(skill));
    render();
  }

  function caseById(id){
    const direct = CASE_LIBRARY.find(item => item.id === id);
    if(direct) return direct;
    for(const capability of catalogCapabilities()){
      const match = casesForCapability(capability.id).find(item => item.id === id);
      if(match) return match;
    }
    return null;
  }

  function selectCase(id){
    const item = caseById(id);
    if(!item) return;
    if(item.capability && catalogCapabilities().some(capability => capability.id === item.capability)){
      state.selectedCapability = item.capability;
      storeCapability(item.capability);
    }
    state.selectedCaseId = item.id;
    const matchingSkill = normalizedSkills().find(skill => skill.name === item.skillName);
    const fallbackCapability = capabilityFor(item.capability);
    const caseLabel = localize(item.title, item.id);
    const skill = matchingSkill
      ? {...matchingSkill, capability:item.capability || matchingSkill.capability, label:caseLabel, icon:item.icon || matchingSkill.icon}
      : {
        name: item.skillName || item.id,
        capability: item.capability,
        label: caseLabel,
        icon: item.icon || fallbackCapability.icon,
        disabled: false,
        raw: {}
      };
    state.selectedSkillName = matchingSkill ? matchingSkill.name : '';
    applyComposerSelection(skill.label, buildSkillPrompt(skill));
    render();
  }

  function rotateCases(){
    state.caseBatchIndex += 1;
    storeCaseBatch(state.caseBatchIndex);
    state.selectedCaseId = '';
    renderCases();
  }

  function dictionaryZhValue(section, key, path, fallback){
    const entry = dictionaryEntry(section, key) || {};
    const value = path === 'label.zh' ? entry.label : (path === 'desc.zh' ? entry.desc : entry);
    if(value && typeof value === 'object'){
      if(typeof value.zh === 'string' && value.zh.trim()) return value.zh;
      if(typeof value.en === 'string' && value.en.trim()) return value.en;
    }
    return fallback || '';
  }

  function dictionaryManagerRows(){
    const rows = [];
    const seenAgents = new Set();
    normalizeProfileRows(state.profiles).forEach(profile => {
      const key = String(profile.name || 'default').trim() || 'default';
      if(seenAgents.has(key)) return;
      seenAgents.add(key);
      rows.push({
        section:'agents',
        type:t('dict_agents'),
        key,
        source:key,
        labelPath:'zh',
        labelValue:dictionaryZhValue('agents', key, 'zh', translateAgentName(key, key)),
        descPath:'',
        descValue:''
      });
    });
    const seenCategories = new Set();
    catalogCapabilities().forEach(capability => {
      const key = String(capability.id || '').trim();
      if(!key || seenCategories.has(key)) return;
      seenCategories.add(key);
      rows.push({
        section:'capabilities',
        type:t('dict_categories'),
        key,
        source:key,
        labelPath:'zh',
        labelValue:dictionaryZhValue('capabilities', key, 'zh', translateGuideEntry('capabilities', key, prettifyDictionaryKey(key))),
        descPath:'',
        descValue:''
      });
    });
    normalizedSkills().forEach(skill => {
      rows.push({
        section:'skills',
        type:t('dict_skills'),
        key:skill.name,
        source:skill.name,
        labelPath:'label.zh',
        labelValue:dictionaryZhValue('skills', skill.name, 'label.zh', skill.label),
        descPath:'desc.zh',
        descValue:dictionaryZhValue('skills', skill.name, 'desc.zh', skill.desc)
      });
    });
    return rows;
  }

  function dictionaryFilterOptions(){
    return [
      {section:'all', label:t('dict_filter_all')},
      {section:'agents', label:t('dict_agents')},
      {section:'capabilities', label:t('dict_categories')},
      {section:'skills', label:t('dict_skills')}
    ];
  }

  function dictionarySearchText(row){
    return [row.type, row.source, row.labelValue, row.descValue]
      .map(value => String(value || '').trim().toLowerCase())
      .filter(Boolean)
      .join(' ');
  }

  function applyDictionaryFilters(overlay){
    if(!overlay) return;
    const activeButton = overlay.querySelector('.session-guide-dict-filter[aria-pressed="true"]');
    const section = activeButton ? String(activeButton.dataset.dictFilter || 'all') : 'all';
    const search = overlay.querySelector('#sessionGuideDictSearch');
    const query = String(search && search.value || '').trim().toLowerCase();
    let visible = 0;
    overlay.querySelectorAll('.session-guide-dict-row').forEach(row => {
      const sectionMatches = section === 'all' || row.dataset.dictSection === section;
      const values = Array.from(row.querySelectorAll('.session-guide-dict-input'))
        .map(input => input.value)
        .join(' ')
        .toLowerCase();
      const searchTarget = `${row.dataset.dictSearch || ''} ${values}`.toLowerCase();
      const queryMatches = !query || searchTarget.includes(query);
      const show = sectionMatches && queryMatches;
      row.hidden = !show;
      if(show) visible += 1;
    });
    const empty = overlay.querySelector('#sessionGuideDictEmpty');
    if(empty) empty.hidden = visible !== 0;
  }

  function setGuideDictionaryValue(section, key, path, value){
    const cleanSection = String(section || '').trim();
    const cleanKey = String(key || '').trim();
    const cleanValue = String(value || '').trim();
    if(!cleanSection || !cleanKey || !path) return;
    if(!customGuideTranslations[cleanSection]) customGuideTranslations[cleanSection] = {};
    if(!customGuideTranslations[cleanSection][cleanKey]) customGuideTranslations[cleanSection][cleanKey] = {};
    const entry = customGuideTranslations[cleanSection][cleanKey];
    if(path === 'zh'){
      if(cleanValue) entry.zh = cleanValue;
      else delete entry.zh;
    }else{
      const [group] = path.split('.');
      if(!entry[group]) entry[group] = {};
      if(cleanValue) entry[group].zh = cleanValue;
      else delete entry[group].zh;
      if(!Object.keys(entry[group]).length) delete entry[group];
    }
    if(!Object.keys(entry).length) delete customGuideTranslations[cleanSection][cleanKey];
    if(!Object.keys(customGuideTranslations[cleanSection]).length) delete customGuideTranslations[cleanSection];
  }

  function closeDictionaryManager(){
    const existing = document.getElementById('sessionGuideDictionaryModal');
    if(existing && existing.parentNode) existing.parentNode.removeChild(existing);
  }

  function openDictionaryManager(){
    closeDictionaryManager();
    const rows = dictionaryManagerRows();
    const overlay = document.createElement('div');
    overlay.className = 'session-guide-dict-overlay';
    overlay.id = 'sessionGuideDictionaryModal';
    overlay.innerHTML = `
      <div class="session-guide-dict-modal" role="dialog" aria-modal="true" aria-labelledby="sessionGuideDictTitle">
        <div class="session-guide-dict-head">
          <h3 id="sessionGuideDictTitle">${escapeHtml(t('dictionary_title'))}</h3>
          <button type="button" class="session-guide-dict-close" data-session-guide-dict-close aria-label="${escapeHtml(t('dict_close'))}">${icon('x', 16)}</button>
        </div>
        <div class="session-guide-dict-filters">
          <div class="session-guide-dict-filter-group" role="group" aria-label="${escapeHtml(t('dict_filter_group'))}">
            ${dictionaryFilterOptions().map(option => `
              <button type="button" class="session-guide-dict-filter" data-dict-filter="${escapeHtml(option.section)}" aria-pressed="${option.section === 'all' ? 'true' : 'false'}">${escapeHtml(option.label)}</button>`).join('')}
          </div>
          <label class="session-guide-dict-search" for="sessionGuideDictSearch">
            <span aria-hidden="true">${icon('search', 14)}</span>
            <input id="sessionGuideDictSearch" type="search" autocomplete="off" aria-label="${escapeHtml(t('dict_filter_search'))}" placeholder="${escapeHtml(t('dict_filter_placeholder'))}">
          </label>
        </div>
        <div class="session-guide-dict-table-wrap">
          <table class="session-guide-dict-table">
            <thead>
              <tr>
                <th>${escapeHtml(t('dict_type'))}</th>
                <th>${escapeHtml(t('dict_source'))}</th>
                <th>${escapeHtml(t('dict_target'))}</th>
                <th>${escapeHtml(t('dict_description'))}</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(row => `
                <tr class="session-guide-dict-row" data-dict-section="${escapeHtml(row.section)}" data-dict-search="${escapeHtml(dictionarySearchText(row))}">
                  <td><span class="session-guide-dict-badge">${escapeHtml(row.type)}</span></td>
                  <td><code>${escapeHtml(row.source)}</code></td>
                  <td><input class="session-guide-dict-input" data-dict-section="${escapeHtml(row.section)}" data-dict-key="${escapeHtml(row.key)}" data-dict-path="${escapeHtml(row.labelPath)}" value="${escapeHtml(row.labelValue)}"></td>
                  <td>${row.descPath ? `<input class="session-guide-dict-input" data-dict-section="${escapeHtml(row.section)}" data-dict-key="${escapeHtml(row.key)}" data-dict-path="${escapeHtml(row.descPath)}" value="${escapeHtml(row.descValue)}">` : ''}</td>
                </tr>`).join('')}
              <tr id="sessionGuideDictEmpty" class="session-guide-dict-empty" hidden><td colspan="4">${escapeHtml(t('dict_no_matches'))}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="session-guide-dict-actions">
          <button type="button" class="session-guide-dict-secondary" data-session-guide-dict-close>${escapeHtml(t('dict_close'))}</button>
          <button type="button" class="session-guide-dict-primary" id="sessionGuideDictSave">${escapeHtml(t('dict_save'))}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', event => {
      if(event.target === overlay || event.target.closest('[data-session-guide-dict-close]')) closeDictionaryManager();
    });
    overlay.querySelectorAll('.session-guide-dict-filter').forEach(button => {
      button.addEventListener('click', () => {
        overlay.querySelectorAll('.session-guide-dict-filter').forEach(item => item.setAttribute('aria-pressed', item === button ? 'true' : 'false'));
        applyDictionaryFilters(overlay);
      });
    });
    const search = overlay.querySelector('#sessionGuideDictSearch');
    if(search) search.addEventListener('input', () => applyDictionaryFilters(overlay));
    const save = overlay.querySelector('#sessionGuideDictSave');
    if(save){
      save.addEventListener('click', () => {
        overlay.querySelectorAll('.session-guide-dict-input').forEach(input => {
          setGuideDictionaryValue(input.dataset.dictSection, input.dataset.dictKey, input.dataset.dictPath, input.value);
        });
        writeStoredGuideDictionary();
        render();
        if(typeof showToast === 'function') showToast(t('dict_saved'));
        closeDictionaryManager();
      });
    }
    const first = overlay.querySelector('#sessionGuideDictSearch') || overlay.querySelector('.session-guide-dict-input');
    if(first && typeof first.focus === 'function') setTimeout(() => first.focus(), 30);
  }

  function bind(rootElement){
    if(rootElement.dataset.sessionGuideBound === '1') return;
    rootElement.dataset.sessionGuideBound = '1';
    rootElement.addEventListener('click', event => {
      const rotate = event.target.closest('#sessionGuideRotateCases');
      if(rotate){
        rotateCases();
        return;
      }
      const dictionary = event.target.closest('#sessionGuideDictionaryBtn');
      if(dictionary){
        openDictionaryManager();
        return;
      }
      const agentButton = event.target.closest('[data-session-guide-agent]');
      if(agentButton){
        void selectAgent(agentButton.dataset.sessionGuideAgent);
        return;
      }
      const capabilityButton = event.target.closest('[data-session-guide-capability]');
      if(capabilityButton){
        setCapability(capabilityButton.dataset.sessionGuideCapability);
        return;
      }
      const skillButton = event.target.closest('[data-session-guide-skill]');
      if(skillButton && !skillButton.disabled){
        selectSkillByName(skillButton.dataset.sessionGuideSkill);
        return;
      }
      const caseButton = event.target.closest('[data-session-guide-case]');
      if(caseButton){
        selectCase(caseButton.dataset.sessionGuideCase);
      }
    });
  }

  function init(){
    const rootElement = root();
    syncShellScrollState();
    if(!rootElement || rootElement.classList.contains('workspace-empty-state') || !guide()) return false;
    rootElement.classList.add('session-guide-active');
    bind(rootElement);
    syncShellScrollState();
    render();
    void bootstrap();
    if(!rootElement._sessionGuideObserver && typeof MutationObserver !== 'undefined'){
      rootElement._sessionGuideObserver = new MutationObserver(() => { init(); });
      rootElement._sessionGuideObserver.observe(rootElement, {childList: true});
    }
    if(!rootElement._sessionGuideVisibilityObserver && typeof MutationObserver !== 'undefined'){
      rootElement._sessionGuideVisibilityObserver = new MutationObserver(syncShellScrollState);
      rootElement._sessionGuideVisibilityObserver.observe(rootElement, {attributes: true, attributeFilter: ['style', 'class']});
    }
    const html = document.documentElement;
    if(html && !html._sessionGuideLocaleObserver && typeof MutationObserver !== 'undefined'){
      html._sessionGuideLocaleObserver = new MutationObserver(() => {
        if(guide()) render();
      });
      html._sessionGuideLocaleObserver.observe(html, {attributes: true, attributeFilter: ['lang']});
    }
    return true;
  }

  function invalidateSkills(){
    if(typeof S !== 'undefined' && S && S.activeProfile) state.activeProfile = S.activeProfile;
    state.skills = [];
    state.skillsError = false;
    const rootElement = root();
    if(rootElement && guide() && !rootElement.classList.contains('workspace-empty-state')) void loadSkills(true);
    else render();
  }

  function refreshSkills(){
    return Promise.all([loadProfiles(true), loadSkills(true)]);
  }

  window.SessionGuide = {init, invalidateSkills, refreshSkills};
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
