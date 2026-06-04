let _knowledgeTreeData = null;
let _knowledgeSearchTimer = null;
let _knowledgeSearchQuery = '';
let _knowledgeExpanded = new Set();
let _knowledgeCurrentNote = null;
let _knowledgePreEditSnapshot = null;
let _knowledgeMode = 'empty'; // empty | read | create | edit
let _knowledgeDirty = false;
let _knowledgeActiveDir = '.';
let _knowledgeActivePath = '';
let _knowledgeEditorTocTimer = null;

function _knowledgeExpandedKey(){
  return 'hermes-webui-knowledge-expanded';
}

function _knowledgeLastNoteKey(){
  return 'hermes-webui-knowledge-last-note';
}

function _loadKnowledgeExpanded(){
  try{
    const raw=localStorage.getItem(_knowledgeExpandedKey());
    _knowledgeExpanded=raw?new Set(JSON.parse(raw)):new Set();
  }catch(e){
    _knowledgeExpanded=new Set();
  }
}

function _saveKnowledgeExpanded(){
  try{
    localStorage.setItem(_knowledgeExpandedKey(), JSON.stringify([..._knowledgeExpanded]));
  }catch(e){}
}

function _loadKnowledgeLastNote(){
  try{
    return localStorage.getItem(_knowledgeLastNoteKey())||'';
  }catch(e){
    return '';
  }
}

function _saveKnowledgeLastNote(path){
  try{
    if(path) localStorage.setItem(_knowledgeLastNoteKey(), path);
    else localStorage.removeItem(_knowledgeLastNoteKey());
  }catch(e){}
}

function _knowledgeFormatTime(ts){
  if(!ts) return '';
  const d=new Date(Number(ts)*1000);
  if(Number.isNaN(d.getTime())) return '';
  return d.toLocaleString();
}

function _knowledgeStripInlineMarkdown(text){
  return String(text||'')
    .replace(/!\[([^\]]*)\]\([^\)]*\)/g,'$1')
    .replace(/\[([^\]]+)\]\([^\)]*\)/g,'$1')
    .replace(/`([^`]+)`/g,'$1')
    .replace(/[*_~#<>]/g,'')
    .trim();
}

function _knowledgeExtractHeadings(markdown){
  const lines=String(markdown||'').split(/\r?\n/);
  const headings=[];
  let fenced=false;
  for(let i=0;i<lines.length;i++){
    const line=lines[i]||'';
    if(/^\s*(```|~~~)/.test(line)){
      fenced=!fenced;
      continue;
    }
    if(fenced) continue;
    const m=line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if(!m) continue;
    const text=_knowledgeStripInlineMarkdown(m[2]);
    if(!text) continue;
    headings.push({level:m[1].length,text,line:i,id:'knowledge-heading-'+headings.length});
  }
  return headings;
}

function _knowledgeRenderToc(mount, headings, onJump){
  if(!mount) return;
  const items=Array.isArray(headings)?headings:[];
  if(!items.length){
    mount.innerHTML='<div class="knowledge-toc-empty">无标题</div>';
    return;
  }
  mount.innerHTML='';
  for(const h of items){
    const btn=document.createElement('button');
    btn.type='button';
    btn.className='knowledge-toc-item level-'+h.level;
    btn.textContent=h.text;
    btn.onclick=()=>onJump&&onJump(h);
    mount.appendChild(btn);
  }
}

function _knowledgeAssignHeadingIds(contentEl, headings){
  if(!contentEl) return;
  const nodes=contentEl.querySelectorAll('h1,h2,h3,h4,h5,h6');
  headings.forEach((h,idx)=>{
    const el=nodes[idx];
    if(el) el.id=h.id;
  });
}

function _knowledgeNormalizeVaultPath(parts){
  const out=[];
  for(const raw of parts){
    const part=String(raw||'').trim();
    if(!part||part==='.') continue;
    if(part==='..') out.pop();
    else out.push(part);
  }
  return out.join('/');
}

function _knowledgeResolveMediaMarkdown(markdown, notePath){
  const baseParts=String(notePath||'').split('/').slice(0,-1);
  return String(markdown||'').replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,(all,alt,url)=>{
    const raw=String(url||'').trim();
    if(!raw || /^(https?:\/\/|api\/notes\/media\?|data:|mailto:|tel:|#)/i.test(raw)) return all;
    const resolved=_knowledgeNormalizeVaultPath([...baseParts, ...raw.split('/')]);
    if(!resolved) return all;
    return `![${alt}](api/notes/media?path=${encodeURIComponent(resolved)})`;
  });
}

function _knowledgeRefreshEditorToc(){
  const textarea=$('knowledgeFormContent');
  const toc=$('knowledgeEditorTocList');
  if(!textarea||!toc) return;
  const headings=_knowledgeExtractHeadings(textarea.value||'');
  _knowledgeRenderToc(toc, headings, h=>_knowledgeScrollTextareaToLine(textarea,h.line));
}

function _knowledgeQueueEditorTocRefresh(){
  if(_knowledgeEditorTocTimer) clearTimeout(_knowledgeEditorTocTimer);
  _knowledgeEditorTocTimer=setTimeout(_knowledgeRefreshEditorToc, 80);
}

function _knowledgeScrollTextareaToLine(textarea, line){
  if(!textarea) return;
  const lines=textarea.value.split(/\n/);
  let pos=0;
  for(let i=0;i<line&&i<lines.length;i++) pos += lines[i].length + 1;
  textarea.focus();
  textarea.setSelectionRange(pos, pos + (lines[line]||'').length);
  const lh=parseFloat(getComputedStyle(textarea).lineHeight)||20;
  textarea.scrollTop=Math.max(0,(line-2)*lh);
}

function _knowledgeSetHeaderButtons(mode){
  const show = id => { const el=$(id); if(el) el.style.display=''; };
  const hide = id => { const el=$(id); if(el) el.style.display='none'; };
  if(mode==='read'){
    show('btnDownloadKnowledgeNote');
    show('btnEditKnowledgeNote');
    show('btnDeleteKnowledgeNote');
    hide('btnCancelKnowledgeNote');
    hide('btnSaveKnowledgeNote');
  }else if(mode==='create' || mode==='edit'){
    hide('btnDownloadKnowledgeNote');
    hide('btnEditKnowledgeNote');
    hide('btnDeleteKnowledgeNote');
    show('btnCancelKnowledgeNote');
    show('btnSaveKnowledgeNote');
  }else{
    hide('btnDownloadKnowledgeNote');
    hide('btnEditKnowledgeNote');
    hide('btnDeleteKnowledgeNote');
    hide('btnCancelKnowledgeNote');
    hide('btnSaveKnowledgeNote');
  }
}

function _knowledgeSetEmptyState(title, sub){
  const titleEl=$('knowledgeDetailTitle');
  const metaEl=$('knowledgeDetailMeta');
  const body=$('knowledgeDetailBody');
  const empty=$('knowledgeDetailEmpty');
  if(titleEl) titleEl.textContent=title||'';
  if(metaEl) metaEl.textContent='';
  if(body){ body.style.display='none'; body.innerHTML=''; }
  if(empty) empty.style.display='';
  _knowledgeMode='empty';
  _knowledgeDirty=false;
  _knowledgeCurrentNote=null;
  _knowledgePreEditSnapshot=null;
  _knowledgeSetHeaderButtons('empty');
  if(titleEl&&sub&&empty){
    const subEl=empty.querySelector('.main-view-empty-sub');
    if(subEl) subEl.textContent=sub;
  }
}

function _knowledgeRenderNoteContent(note){
  const titleEl=$('knowledgeDetailTitle');
  const metaEl=$('knowledgeDetailMeta');
  const body=$('knowledgeDetailBody');
  const empty=$('knowledgeDetailEmpty');
  if(titleEl) titleEl.textContent=note.title||note.name||'';
  if(metaEl){
    const parts=[];
    if(note.path) parts.push(note.path);
    if(note.mtime) parts.push(_knowledgeFormatTime(note.mtime));
    if(typeof note.size==='number') parts.push(String(note.size)+' B');
    metaEl.textContent=parts.join(' · ');
  }
  if(body){
    body.style.display='';
    const headings=_knowledgeExtractHeadings(note.content||'');
    const rendered=renderMd(_knowledgeResolveMediaMarkdown(note.content||'', note.path||''));
    body.innerHTML=`
      <div class="knowledge-detail-layout">
        <div class="main-view-content knowledge-note-content">${rendered}</div>
        <aside class="knowledge-toc" aria-label="Headings">
          <div class="knowledge-toc-title">目录</div>
          <div class="knowledge-toc-list" id="knowledgeReadTocList"></div>
        </aside>
      </div>`;
    const contentEl=body.querySelector('.knowledge-note-content');
    _knowledgeAssignHeadingIds(contentEl, headings);
    _knowledgeRenderToc(body.querySelector('#knowledgeReadTocList'), headings, h=>{
      const target=document.getElementById(h.id);
      if(target) target.scrollIntoView({block:'start',behavior:'smooth'});
    });
    requestAnimationFrame(()=>{ if(typeof renderKatexBlocks==='function') renderKatexBlocks(); });
  }
  if(empty) empty.style.display='none';
  _knowledgeMode='read';
  _knowledgeDirty=false;
  _knowledgeSetHeaderButtons('read');
}

function _knowledgeRenderForm({mode, note, content, title, category}){
  const titleEl=$('knowledgeDetailTitle');
  const metaEl=$('knowledgeDetailMeta');
  const body=$('knowledgeDetailBody');
  const empty=$('knowledgeDetailEmpty');
  if(!body||!titleEl) return;
  titleEl.textContent=mode==='edit' ? '编辑笔记' : '新建笔记';
  if(metaEl) metaEl.textContent=note && note.path ? note.path : '';
  const targetCategory = category || _knowledgeActiveDir || '.';
  const titleDisabled = mode==='edit' ? 'disabled' : '';
  const titleHint = mode==='edit'
    ? `<div class="detail-form-hint">编辑模式仅修改正文；如需重命名或移动目录，请新建后删除旧笔记。</div>`
    : '';
  const currentBody = content != null ? content : (note && note.content) || '';
  body.style.display='';
  body.innerHTML = `
    <div class="main-view-content knowledge-editor-shell">
      <form class="detail-form knowledge-editor-form" onsubmit="event.preventDefault(); saveKnowledgeNote();">
        <div class="knowledge-form-grid">
          <div class="detail-form-row">
            <label for="knowledgeFormTitle">标题</label>
            <input type="text" id="knowledgeFormTitle" value="${esc(title || '')}" placeholder="示例：登录失败排查" autocomplete="off" ${titleDisabled} required>
            ${titleHint}
          </div>
          <div class="detail-form-row">
            <label for="knowledgeFormCategory">目录</label>
            <input type="text" id="knowledgeFormCategory" value="${esc(targetCategory)}" placeholder="01-故障知识库" autocomplete="off">
          </div>
        </div>
        <div class="detail-form-row" style="margin-top:12px">
          <div class="knowledge-editor-label-row">
            <label for="knowledgeFormContent">正文</label>
            <button type="button" class="knowledge-inline-tool" onclick="openKnowledgeImageUpload()" title="插入图片">${li('image-plus', 13)}<span>图片</span></button>
          </div>
          <textarea id="knowledgeFormContent" class="knowledge-edit-textarea" rows="22" spellcheck="false">${esc(currentBody)}</textarea>
        </div>
        <div id="knowledgeFormError" class="detail-form-error" style="display:none"></div>
      </form>
      <aside class="knowledge-toc knowledge-editor-toc" aria-label="Headings">
        <div class="knowledge-toc-title">目录</div>
        <div class="knowledge-toc-list" id="knowledgeEditorTocList"></div>
      </aside>
    </div>`;
  if(empty) empty.style.display='none';
  _knowledgeMode=mode;
  _knowledgeDirty=(mode==='create' || mode==='edit');
  _knowledgeSetHeaderButtons(mode);
  const focusEl = mode==='edit' ? $('knowledgeFormContent') : $('knowledgeFormTitle');
  const textarea=$('knowledgeFormContent');
  if(textarea){
    textarea.addEventListener('input',()=>{ _knowledgeDirty=true; _knowledgeQueueEditorTocRefresh(); });
    textarea.addEventListener('paste', _knowledgeHandleEditorPaste);
    _knowledgeRefreshEditorToc();
  }
  if(focusEl) focusEl.focus();
}

function _knowledgeTreeNodePath(node){
  return node.path && node.path !== '.' ? node.path : '';
}

function _knowledgeNodeIndent(depth){
  return 8 + depth * 14;
}

function _knowledgeIconForNode(node){
  if(node.type==='dir') return li('folder', 14);
  return li('file-text', 14);
}

function _knowledgeChildren(node){
  return Array.isArray(node.children) ? node.children : [];
}

function _knowledgeRenderNodes(nodes, depth, mount){
  for(const node of nodes){
    if(!node) continue;
    const row=document.createElement('div');
    row.className='knowledge-tree-row';
    const nodePath=_knowledgeTreeNodePath(node);
    row.style.paddingLeft=_knowledgeNodeIndent(depth)+'px';
    row.dataset.path=nodePath;
    row.dataset.type=node.type || 'note';
    const isActivePath = node.type==='note'
      ? _knowledgeActivePath === nodePath
      : _knowledgeActiveDir === nodePath || (nodePath === '' && _knowledgeActiveDir === '.');
    if(isActivePath) row.classList.add('active');

    if(node.type==='dir'){
      const expanded = nodePath ? _knowledgeExpanded.has(nodePath) : true;
      if(expanded) row.classList.add('expanded');
      row.innerHTML = `
        <span class="knowledge-chevron">${li('chevron-right', 12)}</span>
        <span class="knowledge-row-icon">${li('folder', 14)}</span>
        <span class="knowledge-row-text">${esc(node.name || node.path || 'vault')}</span>
        <span class="knowledge-row-actions">
          <button type="button" title="新建子目录" aria-label="新建子目录" data-action="mkdir">${li('folder-plus', 12)}</button>
          <button type="button" title="重命名目录" aria-label="重命名目录" data-action="rename">${li('pencil', 12)}</button>
          <button type="button" title="删除目录" aria-label="删除目录" data-action="delete">${li('trash-2', 12)}</button>
        </span>
      `;
      row.onclick = () => {
        if(nodePath){
          _knowledgeActiveDir = nodePath;
          if(_knowledgeExpanded.has(nodePath)) _knowledgeExpanded.delete(nodePath);
          else _knowledgeExpanded.add(nodePath);
          _saveKnowledgeExpanded();
          _renderKnowledgeTree();
        }
      };
      row.querySelector('[data-action="mkdir"]')?.addEventListener('click', e=>{
        e.stopPropagation();
        createKnowledgeDirectory(nodePath);
      });
      row.querySelector('[data-action="rename"]')?.addEventListener('click', e=>{
        e.stopPropagation();
        if(nodePath) renameKnowledgeDirectory(nodePath);
      });
      row.querySelector('[data-action="delete"]')?.addEventListener('click', e=>{
        e.stopPropagation();
        if(nodePath) deleteKnowledgeDirectory(nodePath);
      });
      mount.appendChild(row);
      const childrenWrap=document.createElement('div');
      childrenWrap.style.display = expanded || !nodePath ? '' : 'none';
      childrenWrap.dataset.dirChildren = nodePath || '.';
      mount.appendChild(childrenWrap);
      if(expanded || !nodePath){
        _knowledgeRenderNodes(_knowledgeChildren(node), depth + 1, childrenWrap);
      }
      continue;
    }

    row.innerHTML = `
      <span class="knowledge-chevron" style="opacity:0">${li('chevron-right', 12)}</span>
      <span class="knowledge-row-icon">${li('file-text', 14)}</span>
      <span class="knowledge-row-text">${esc(node.title || node.name || '')}</span>
    `;
    row.onclick = () => openKnowledgeNote(node.path, row);
    mount.appendChild(row);
  }
}

function _renderKnowledgeTree(){
  const box=$('knowledgeList');
  if(!box) return;
  const data=_knowledgeTreeData || {};
  const tree=Array.isArray(data.tree) ? data.tree : [];
  box.innerHTML='';
  if(!tree.length){
    box.innerHTML='<div class="knowledge-tree-empty">暂无笔记。点击“新建”创建第一条 Markdown 笔记。</div>';
    return;
  }
  const mount=document.createElement('div');
  mount.className='knowledge-tree';
  _knowledgeRenderNodes(tree, 0, mount);
  box.appendChild(mount);
}

function _renderKnowledgeSearchResults(results, query){
  const box=$('knowledgeList');
  if(!box) return;
  if(!query){
    _renderKnowledgeTree();
    return;
  }
  if(!results.length){
    box.innerHTML='<div class="knowledge-tree-empty">没有匹配的笔记。</div>';
    return;
  }
  box.innerHTML='';
  for(const note of results){
    const row=document.createElement('div');
    row.className='knowledge-search-match';
    row.innerHTML = `
      <div class="knowledge-search-title">${esc(note.title || note.name || '')}</div>
      <div class="knowledge-search-path">${esc(note.path || '')}</div>
      <div class="knowledge-search-snippet">${esc(note.snippet || '')}</div>
    `;
    row.onclick = () => openKnowledgeNote(note.path, null);
    box.appendChild(row);
  }
}

async function loadKnowledgeNotes(force=false){
  const box=$('knowledgeList');
  if(!box) return;
  if(!_knowledgeExpanded.size) _loadKnowledgeExpanded();
  try{
    if(force && _knowledgeDirty){
      const ok = await _knowledgeConfirmDiscard();
      if(!ok) return;
      cancelKnowledgeEdit();
    }
    const data = await api('/api/notes/tree');
    _knowledgeTreeData = data || {};
    const expandedNow = new Set(_knowledgeExpanded);
    if(!expandedNow.size && Array.isArray(_knowledgeTreeData.tree)){
      for(const node of _knowledgeTreeData.tree){
        if(node && node.type==='dir' && node.path) expandedNow.add(node.path);
      }
      _knowledgeExpanded = expandedNow;
      _saveKnowledgeExpanded();
    }
    if(_knowledgeSearchQuery){
      await filterKnowledgeNotes(true);
    }else{
      _renderKnowledgeTree();
    }
    const lastNote = _knowledgeCurrentNote ? _knowledgeCurrentNote.path : _loadKnowledgeLastNote();
    if((force || !_knowledgeCurrentNote) && lastNote){
      const found = (_knowledgeTreeData.notes || []).find(n => n.path === lastNote);
      if(found){
        await openKnowledgeNote(lastNote, null, {silent: true});
      }
    }else if(!_knowledgeCurrentNote && _knowledgeMode === 'empty'){
      _knowledgeSetEmptyState('选择一个笔记', '从左侧知识库目录选择笔记，或新建一条 Markdown 笔记。');
    }
  }catch(e){
    box.innerHTML = `<div class="knowledge-error">加载知识库失败：${esc(e.message)}</div>`;
  }
}

function filterKnowledgeNotes(force=false){
  const input=$('knowledgeSearch');
  const query=(input&&input.value||'').trim();
  _knowledgeSearchQuery=query;
  if(_knowledgeSearchTimer) clearTimeout(_knowledgeSearchTimer);
  if(!query){
    _renderKnowledgeTree();
    return;
  }
  _knowledgeSearchTimer=setTimeout(async()=>{
    try{
      const data=await api('/api/notes/search?q='+encodeURIComponent(query));
      _renderKnowledgeSearchResults(Array.isArray(data.results)?data.results:[], query);
    }catch(e){
      const box=$('knowledgeList');
      if(box) box.innerHTML = `<div class="knowledge-error">搜索失败：${esc(e.message)}</div>`;
    }
  }, force ? 0 : 300);
}

async function _knowledgeConfirmDiscard(){
  if(!_knowledgeDirty) return true;
  return showConfirmDialog({
    title: '放弃未保存更改？',
    message: '当前笔记有未保存内容，继续操作会丢失本次修改。',
    confirmLabel: '放弃',
    cancelLabel: '取消',
    danger: true,
    focusCancel: true,
  });
}

async function confirmKnowledgeNavigation(){
  return _knowledgeConfirmDiscard();
}

async function openKnowledgeNote(path, el, opts={}){
  const notePath = String(path || '').trim();
  if(!notePath) return;
  if(_knowledgeDirty){
    const ok = await _knowledgeConfirmDiscard();
    if(!ok) return;
  }
  try{
    const data = await api('/api/notes/content?path='+encodeURIComponent(notePath));
    _knowledgeCurrentNote = data;
    _knowledgeActivePath = notePath;
    const parts = notePath.split('/');
    _knowledgeActiveDir = parts.length > 1 ? parts.slice(0, -1).join('/') : '.';
    _knowledgePreEditSnapshot = null;
    _knowledgeRenderNoteContent(data);
    _saveKnowledgeLastNote(notePath);
    if(!(_knowledgeSearchQuery && _knowledgeSearchQuery.trim())) _renderKnowledgeTree();
    document.querySelectorAll('.knowledge-tree-row.active').forEach(n => n.classList.remove('active'));
    if(el) el.classList.add('active');
    if(!opts.silent && _knowledgeSearchQuery){
      filterKnowledgeNotes(true);
    }
  }catch(e){
    showToast('加载笔记失败：' + e.message);
  }
}

function openKnowledgeCreate(){
  if(typeof switchPanel==='function' && _currentPanel!=='knowledge'){
    switchPanel('knowledge',{fromRailClick:true}).then(()=>{
      if(_currentPanel==='knowledge') openKnowledgeCreate();
    });
    return;
  }
  if(!_knowledgeTreeData) _loadKnowledgeExpanded();
  const okPromise = _knowledgeConfirmDiscard();
  Promise.resolve(okPromise).then(ok => {
    if(!ok) return;
    _knowledgePreEditSnapshot = _knowledgeCurrentNote ? {..._knowledgeCurrentNote} : null;
    const defaultCategory = _knowledgeActiveDir && _knowledgeActiveDir !== '.' ? _knowledgeActiveDir : ((_knowledgeTreeData && Array.isArray(_knowledgeTreeData.default_categories) && _knowledgeTreeData.default_categories[0]) || '01-故障知识库');
    _knowledgeCurrentNote = null;
    _knowledgeActivePath = '';
    _knowledgeRenderForm({mode:'create', note:null, title:'', category:defaultCategory, content:'# 新笔记\n'});
  });
}

function editCurrentKnowledgeNote(){
  if(!_knowledgeCurrentNote) return;
  _knowledgePreEditSnapshot = {..._knowledgeCurrentNote};
  _knowledgeRenderForm({
    mode:'edit',
    note:_knowledgeCurrentNote,
    title:_knowledgeCurrentNote.title || _knowledgeCurrentNote.name || '',
    category:(_knowledgeCurrentNote.category || _knowledgeActiveDir || '.'),
    content:_knowledgeCurrentNote.content || '',
  });
}

function cancelKnowledgeEdit(){
  if(_knowledgePreEditSnapshot){
    const snap=_knowledgePreEditSnapshot;
    _knowledgePreEditSnapshot=null;
    _knowledgeCurrentNote=snap;
    _knowledgeRenderNoteContent(snap);
    return;
  }
  _knowledgeMode='empty';
  _knowledgeDirty=false;
  const body=$('knowledgeDetailBody');
  const empty=$('knowledgeDetailEmpty');
  const title=$('knowledgeDetailTitle');
  const meta=$('knowledgeDetailMeta');
  if(body){ body.innerHTML=''; body.style.display='none'; }
  if(empty) empty.style.display='';
  if(title) title.textContent='';
  if(meta) meta.textContent='';
  _knowledgeSetHeaderButtons('empty');
}

async function saveKnowledgeNote(){
  const titleEl=$('knowledgeFormTitle');
  const categoryEl=$('knowledgeFormCategory');
  const contentEl=$('knowledgeFormContent');
  const errEl=$('knowledgeFormError');
  if(!titleEl || !categoryEl || !contentEl || !errEl) return;
  const title=(titleEl.value||'').trim();
  const category=(categoryEl.value||'').trim();
  const content=contentEl.value||'';
  errEl.style.display='none';
  if(!title && _knowledgeMode!=='edit'){
    errEl.textContent='请输入标题。';
    errEl.style.display='';
    return;
  }
  try{
    if(_knowledgeMode==='edit' && _knowledgeCurrentNote){
      const data=await api('/api/notes/content',{method:'POST',body:JSON.stringify({path:_knowledgeCurrentNote.path,content})});
      _knowledgeCurrentNote = data;
      showToast('笔记已保存');
      _knowledgeDirty=false;
      _knowledgePreEditSnapshot=null;
      await loadKnowledgeNotes(true);
      await openKnowledgeNote(data.path,null,{silent:true});
      return;
    }
    const data=await api('/api/notes',{method:'POST',body:JSON.stringify({title,category,content})});
    showToast('笔记已创建');
    _knowledgeDirty=false;
    _knowledgePreEditSnapshot=null;
    _knowledgeCurrentNote = data;
    _knowledgeActivePath = data.path;
    _knowledgeActiveDir = data.category || category || '.';
    await loadKnowledgeNotes(true);
    await openKnowledgeNote(data.path,null,{silent:true});
  }catch(e){
    errEl.textContent='保存失败：'+e.message;
    errEl.style.display='';
  }
}

function _knowledgeEditorTargetDir(){
  const categoryEl=$('knowledgeFormCategory');
  const category=(categoryEl&&categoryEl.value||_knowledgeActiveDir||'.').trim();
  return category && category!=='.' ? category : '';
}

function _knowledgeInsertIntoTextarea(textarea, snippet){
  if(!textarea||!snippet) return;
  const start=textarea.selectionStart||0;
  const end=textarea.selectionEnd||start;
  const value=textarea.value||'';
  const before=value.slice(0,start);
  const after=value.slice(end);
  const needsBefore=before && !before.endsWith('\n') ? '\n' : '';
  const needsAfter=after && !after.startsWith('\n') ? '\n' : '';
  const insert=needsBefore + snippet + needsAfter;
  textarea.value=before + insert + after;
  const cursor=(before + insert).length;
  textarea.focus();
  textarea.setSelectionRange(cursor,cursor);
  _knowledgeDirty=true;
  _knowledgeQueueEditorTocRefresh();
}

async function _knowledgeUploadImageFile(file){
  if(!file) return null;
  const fd=new FormData();
  fd.append('file', file, file.name || 'image.png');
  if(_knowledgeMode==='edit' && _knowledgeCurrentNote && _knowledgeCurrentNote.path){
    fd.append('note_path', _knowledgeCurrentNote.path);
  }else{
    fd.append('target_dir', _knowledgeEditorTargetDir());
  }
  return api('/api/notes/assets',{method:'POST',body:fd,headers:{}});
}

async function _knowledgeHandleEditorPaste(event){
  const items=event.clipboardData && event.clipboardData.items;
  if(!items) return;
  const files=[];
  for(const item of items){
    if(item.kind==='file' && /^image\//i.test(item.type||'')){
      const file=item.getAsFile();
      if(file) files.push(file);
    }
  }
  if(!files.length) return;
  event.preventDefault();
  const textarea=$('knowledgeFormContent');
  try{
    for(const file of files){
      const uploaded=await _knowledgeUploadImageFile(file);
      _knowledgeInsertIntoTextarea(textarea, uploaded && uploaded.markdown);
    }
    showToast('图片已插入');
  }catch(e){
    showToast('图片插入失败：' + e.message);
  }
}

async function openKnowledgeImageUpload(){
  const textarea=$('knowledgeFormContent');
  if(!textarea) return;
  const input=document.createElement('input');
  input.type='file';
  input.accept='image/png,image/jpeg,image/gif,image/webp';
  input.multiple=true;
  input.onchange=async()=>{
    const files=Array.from(input.files||[]);
    if(!files.length) return;
    try{
      for(const file of files){
        const uploaded=await _knowledgeUploadImageFile(file);
        _knowledgeInsertIntoTextarea(textarea, uploaded && uploaded.markdown);
      }
      showToast('图片已插入');
    }catch(e){
      showToast('图片上传失败：' + e.message);
    }
  };
  input.click();
}

async function deleteCurrentKnowledgeNote(){
  if(!_knowledgeCurrentNote) return;
  const ok=await showConfirmDialog({
    title:'删除笔记',
    message:`确定要删除「${_knowledgeCurrentNote.title || _knowledgeCurrentNote.name || ''}」吗？此操作不可恢复。`,
    confirmLabel:'删除',
    cancelLabel:'取消',
    danger:true,
    focusCancel:true,
  });
  if(!ok) return;
  try{
    await api('/api/notes/delete',{method:'POST',body:JSON.stringify({path:_knowledgeCurrentNote.path})});
    showToast('笔记已删除');
    _knowledgeCurrentNote=null;
    _knowledgeActivePath='';
    _saveKnowledgeLastNote('');
    await loadKnowledgeNotes(true);
    _knowledgeSetEmptyState('选择一个笔记', '从左侧知识库目录选择笔记，或新建一条 Markdown 笔记。');
  }catch(e){
    showToast('删除失败：' + e.message);
  }
}

function _knowledgeNormalizeDirectoryParent(parent){
  const value=String(parent||'').trim();
  return value && value!=='.' ? value : '';
}

function createRootKnowledgeDirectory(){
  return createKnowledgeDirectory('');
}

async function createKnowledgeDirectory(parent=''){
  const normalizedParent=_knowledgeNormalizeDirectoryParent(parent);
  const base=normalizedParent || '根目录';
  const name=await showPromptDialog({
    title:'新建目录',
    message:`在 ${base} 下创建目录`,
    placeholder:'目录名称',
    confirmLabel:'创建',
  });
  if(!name) return;
  try{
    const data=await api('/api/notes/directories',{method:'POST',body:JSON.stringify({parent:normalizedParent,name})});
    if(data && data.path) _knowledgeExpanded.add(normalizedParent || data.path);
    _saveKnowledgeExpanded();
    showToast('目录已创建');
    await loadKnowledgeNotes(true);
  }catch(e){
    showToast('创建目录失败：' + e.message);
  }
}

async function renameKnowledgeDirectory(path){
  const current=String(path||'').split('/').pop()||'';
  const name=await showPromptDialog({
    title:'重命名目录',
    message:path,
    value:current,
    placeholder:'目录名称',
    confirmLabel:'重命名',
  });
  if(!name || name===current) return;
  try{
    const previousNotePath=_knowledgeCurrentNote && _knowledgeCurrentNote.path ? _knowledgeCurrentNote.path : '';
    const data=await api('/api/notes/directories',{method:'PUT',body:JSON.stringify({path,name})});
    showToast('目录已重命名');
    if(data && data.path) _knowledgeExpanded.add(data.path);
    _saveKnowledgeExpanded();
    await loadKnowledgeNotes(true);
    if(data && data.path && previousNotePath && previousNotePath.startsWith(path + '/')){
      await openKnowledgeNote(data.path + previousNotePath.slice(path.length), null, {silent:true});
    }
  }catch(e){
    showToast('重命名目录失败：' + e.message);
  }
}

async function deleteKnowledgeDirectory(path){
  if(!path) return;
  const ok=await showConfirmDialog({
    title:'删除目录',
    message:`删除目录「${path}」？如果目录非空，将先尝试安全删除。`,
    confirmLabel:'删除',
    cancelLabel:'取消',
    danger:true,
    focusCancel:true,
  });
  if(!ok) return;
  try{
    await api('/api/notes/directories',{method:'DELETE',body:JSON.stringify({path,recursive:false})});
    showToast('目录已删除');
    _knowledgeExpanded.delete(path);
    _saveKnowledgeExpanded();
    await loadKnowledgeNotes(true);
    if(_knowledgeCurrentNote && _knowledgeCurrentNote.path && _knowledgeCurrentNote.path.startsWith(path + '/')){
      _knowledgeCurrentNote=null;
      _knowledgeActivePath='';
      _saveKnowledgeLastNote('');
      _knowledgeSetEmptyState('选择一个笔记', '从左侧知识库目录选择笔记，或新建一条 Markdown 笔记。');
    }
  }catch(e){
    if(!/not empty|非空|不为空/i.test(e.message||'')){
      showToast('删除目录失败：' + e.message);
      return;
    }
    const recursive=await showConfirmDialog({
      title:'目录非空',
      message:`「${path}」包含文件或子目录，是否递归删除？此操作不可恢复。`,
      confirmLabel:'递归删除',
      cancelLabel:'取消',
      danger:true,
      focusCancel:true,
    });
    if(!recursive) return;
    try{
      await api('/api/notes/directories',{method:'DELETE',body:JSON.stringify({path,recursive:true})});
      showToast('目录已删除');
      _knowledgeExpanded.delete(path);
      _saveKnowledgeExpanded();
      await loadKnowledgeNotes(true);
      if(_knowledgeCurrentNote && _knowledgeCurrentNote.path && _knowledgeCurrentNote.path.startsWith(path + '/')){
        _knowledgeCurrentNote=null;
        _knowledgeActivePath='';
        _saveKnowledgeLastNote('');
        _knowledgeSetEmptyState('选择一个笔记', '从左侧知识库目录选择笔记，或新建一条 Markdown 笔记。');
      }
    }catch(err){
      showToast('删除目录失败：' + err.message);
    }
  }
}

async function downloadCurrentKnowledgeNote(){
  if(!_knowledgeCurrentNote) return;
  const path=_knowledgeCurrentNote.path || '';
  const url=new URL('api/notes/download', document.baseURI || location.href);
  url.searchParams.set('path', path);
  const a=document.createElement('a');
  a.href=url.href;
  a.download=_knowledgeCurrentNote.name || 'note.md';
  a.rel='noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function openKnowledgeUpload(){
  const input=document.createElement('input');
  input.type='file';
  input.accept='.md,.markdown,text/markdown';
  input.multiple=false;
  input.onchange=async ()=>{
    const file=input.files && input.files[0];
    if(!file) return;
    try{
      const fd=new FormData();
      fd.append('file', file, file.name);
      fd.append('target_dir', _knowledgeActiveDir && _knowledgeActiveDir !== '.' ? _knowledgeActiveDir : '');
      await api('/api/notes/upload',{method:'POST',body:fd,headers:{}});
      showToast('Markdown 已上传');
      await loadKnowledgeNotes(true);
    }catch(e){
      showToast('上传失败：' + e.message);
    }
  };
  input.click();
}

async function openKnowledgeOfficeImport(){
  const input=document.createElement('input');
  input.type='file';
  input.accept='.docx,.xlsx,.pptx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation';
  input.multiple=false;
  input.onchange=async()=>{
    const file=input.files && input.files[0];
    if(!file) return;
    try{
      const fd=new FormData();
      fd.append('file', file, file.name);
      fd.append('target_dir', _knowledgeActiveDir && _knowledgeActiveDir !== '.' ? _knowledgeActiveDir : '');
      const data=await api('/api/notes/import',{method:'POST',body:fd,headers:{}});
      showToast('Office 文档已导入');
      await loadKnowledgeNotes(true);
      if(data && data.path) await openKnowledgeNote(data.path,null,{silent:true});
    }catch(e){
      showToast('Office 导入失败：' + e.message);
    }
  };
  input.click();
}
