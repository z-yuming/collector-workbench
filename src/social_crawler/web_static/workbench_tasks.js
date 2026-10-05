/* Persistent task execution and one detail view for all stored results. */
let selectedTaskRecord = null;
let activeTaskRecords = [];
let taskPollBusy = false;
let historyGeneration = 0;
let taskActionSignature = '';
let activeListSignature = '';
const taskRequestKeys = new Map();
const taskStateLabels = {queued:'排队中',running:'处理中',cancelling:'正在取消',success:'完成',partial:'需确认',failed:'失败',cancelled:'已取消',interrupted:'运行中断'};
const runningStates = ['queued','running','cancelling'];

async function taskJSON(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {...options, signal:controller.signal});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.message || '本地服务暂不可用，请稍后重试。');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('连接超时。任务可能仍在后台运行，请查看进行中的任务后再重试。');
    throw error;
  } finally { clearTimeout(timeout); }
}

function taskPost(url, body = {}) {
  return taskJSON(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

function taskButton(label, action) {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'mini-button'; button.textContent = label;
  button.addEventListener('click',async () => {
    button.disabled = true;
    try { await action(); } catch (error) { setStatus('操作未完成',error.message); }
    finally { if (button.isConnected) button.disabled = false; }
  });
  return button;
}

function syncDeviceContext() {
  const needed = activeWorkbenchView === 'collect' && ['adb','ui'].includes(form.mode.value);
  document.getElementById('refreshDevice').classList.toggle('hidden',!needed);
  const detail = document.querySelector('.device-detail');
  if (detail) detail.classList.toggle('hidden',!needed);
  if (needed) deviceText.textContent = '检查手机采集条件';
}

function renderPreflight(source, check) {
  const target = document.getElementById(source === 'video' ? 'videoPreflight' : 'collectPreflight');
  target.replaceChildren(); target.classList.remove('hidden');
  const summary = document.createElement('strong'); summary.textContent = check.ready ? '基础条件可用' : '开始前需要处理以下问题'; target.append(summary);
  for (const item of check.checks) {
    const line = document.createElement('p'); line.className = item.status;
    line.textContent = `${item.label}：${item.message}`; target.append(line);
  }
}

async function checkSelectedTask(source) {
  const payload = source === 'video' ? {action:'parse',url:document.getElementById('videoUrl').value} : payloadFromForm();
  const button = document.getElementById(source === 'video' ? 'checkVideo' : 'checkCollect');
  button.disabled = true;
  try { const check = await taskPost('/api/preflight',{source,payload}); renderPreflight(source,check); return check; }
  catch (error) {
    renderPreflight(source,{ready:false,checks:[{label:'本地服务',status:'blocked',message:error.message}]});
  } finally { button.disabled = false; }
}

async function submitTask(source, payload) {
  const buttons = source === 'video' ? [...document.querySelectorAll('#videoForm button[type="submit"]')] : [runBtn];
  if (buttons.some(button => button.disabled)) return;
  buttons.forEach(button => button.disabled = true);
  const key = source + ':' + JSON.stringify(payload);
  try {
    const check = await taskPost('/api/preflight',{source,payload}); renderPreflight(source,check);
    if (!check.ready) {
      const message = check.checks.find(item => item.status === 'blocked')?.message;
      if (source === 'video') document.getElementById('videoTaskStatus').textContent = message;
      else setStatus('暂时无法开始',message);
      return;
    }
    if (!taskRequestKeys.has(key)) taskRequestKeys.set(key,crypto.randomUUID());
    const result = await taskPost('/api/tasks',{source,payload:check.payload,requestKey:taskRequestKeys.get(key)});
    taskRequestKeys.delete(key);
    selectedTaskRecord = result.task;
    if (source === 'collect') renderTaskDetail(result.task);
    else updateVideoTask(result.task);
    await pollTasks();
    await loadHistory(0);
  } catch (error) {
    if (source === 'video') document.getElementById('videoTaskStatus').textContent = error.message;
    else setStatus('任务未能提交',error.message);
  } finally { buttons.forEach(button => button.disabled = false); }
}

function updateVideoTask(task) {
  document.getElementById('videoTaskStatus').textContent = `${taskStateLabels[task.status] || task.quality?.label || '任务'}：${task.message || task.stage || ''}`;
  document.getElementById('videoMetadata').textContent = formatVideoMetadata(task.metadata);
  const downloads = document.getElementById('videoDownloads'); downloads.replaceChildren();
  for (const [name,href] of Object.entries(task.downloadLinks || {})) downloads.append(exportLink(name,href,{}));
}

function detailSections(showData,showFiles,showLog) {
  document.querySelector('#resultPanel .metrics').classList.toggle('hidden',!showData);
  previewList.parentElement.classList.toggle('hidden',!showData);
  links.parentElement.classList.toggle('hidden',!showFiles);
  document.querySelector('#resultPanel .log-wrap').classList.toggle('hidden',!showLog);
}

function resetDetail() {
  selectedTaskRecord = null; taskActionSignature = '';
  document.getElementById('detailHeading').textContent = '任务详情';
  document.getElementById('detailActions').replaceChildren();
  document.getElementById('detailContext').textContent = '';
  document.getElementById('detailProgress').classList.add('hidden');
  setStatus('选择一条记录','查看任务参数、运行情况、结果预览和下载文件。');
  detailSections(false,false,false);
}

function renderResultPreview(task) {
  if (!task.preview?.table) return renderPreview(task);
  previewList.replaceChildren();
  const wrap = document.createElement('div'); wrap.className = 'data-table-wrap';
  const table = document.createElement('table'); table.className = 'data-table';
  const head = document.createElement('thead'); const header = document.createElement('tr');
  for (const name of task.preview.table.columns) { const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = name; header.append(cell); }
  head.append(header); table.append(head);
  const body = document.createElement('tbody');
  for (const row of task.preview.table.rows.slice(0,20)) {
    const line = document.createElement('tr');
    for (const name of task.preview.table.columns) {
      const cell = document.createElement('td'); const value = row[name];
      cell.textContent = value == null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value); line.append(cell);
    }
    body.append(line);
  }
  table.append(body); wrap.append(table); previewList.append(wrap);
  const note = document.createElement('p'); note.className = 'preview-meta'; note.textContent = `预览前${Math.min(task.preview.table.rows.length,20)}条，完整数据请下载文件。`; previewList.append(note);
}

function renderTaskDetail(task) {
  selectedTaskRecord = task;
  document.getElementById('detailHeading').textContent = '任务详情';
  document.getElementById('detailContext').textContent = `${sourceLabel(task.source)} · ${readablePlatform(task.platform)} · ${task.query || '任务'}`;
  const state = taskStateLabels[task.status] || task.quality?.label || (task.ok ? '完成' : '失败');
  setStatus(state,task.message || task.stage || qualityMessage(task));
  const dataAvailable = Boolean(task.preview?.table?.rows?.length || task.preview?.contents?.length || task.preview?.comments?.length || task.metadata || task.counts?.contents || task.counts?.comments);
  detailSections(dataAvailable,Object.keys(task.downloadLinks || {}).length > 0,true);
  previewList.parentElement.classList.toggle('hidden',!(task.preview?.table?.rows?.length || task.preview?.contents?.length || task.preview?.comments?.length || task.metadata));
  document.getElementById('mComments').closest('.metric').classList.toggle('hidden',!task.counts?.comments);
  document.getElementById('mFiles').closest('.metric').classList.toggle('hidden',!Object.keys(task.downloadLinks || {}).length);
  setMetrics(task); renderResultPreview(task); renderLinks(task);
  const progress = document.getElementById('detailProgress'); progress.replaceChildren();
  progress.classList.toggle('hidden',!runningStates.includes(task.status));
  if (runningStates.includes(task.status)) {
    const text = document.createElement('span'); text.textContent = task.status === 'queued' ? '任务已保存，等待前面的任务完成。可以关闭或刷新页面。' : '任务在后台执行，刷新页面后可继续查看。'; progress.append(text);
    if (task.progress?.total) {
      const bar = document.createElement('progress'); bar.max = task.progress.total; bar.value = task.progress.current; bar.setAttribute('aria-label','已处理数量'); progress.append(bar);
      const count = document.createElement('span'); count.textContent = `已处理 ${task.progress.current}/${task.progress.total}`; progress.append(count);
    }
  }
  log.textContent = JSON.stringify({来源:sourceLabel(task.source),平台:readablePlatform(task.platform),参数:task.payload || {},运行记录:task.events || [],校验:task.validation || {},提示:task.message || task.quality?.warnings || []},null,2);
  const signature = `${task.id}:${task.status}:${task.source}`;
  if (signature !== taskActionSignature) {
    taskActionSignature = signature;
    const actions = document.getElementById('detailActions'); actions.replaceChildren();
    if (task.id.startsWith('task-')) {
      if (['queued','running'].includes(task.status)) actions.append(taskButton('取消任务',async () => { const result = await taskPost(`/api/tasks/${encodeURIComponent(task.id)}/cancel`); renderTaskDetail(result.task); await pollTasks(); }));
      else if (!runningStates.includes(task.status)) actions.append(taskButton('重试任务',() => retryTask(task)));
    } else if (task.payload) actions.append(taskButton('重试任务',() => retryTask(task)));
    if (task.payload && task.source !== 'video') actions.append(taskButton('恢复参数',() => { showWorkbenchView('collect'); applyPayloadToForm(task.payload); syncDeviceContext(); setStatus('参数已恢复','检查参数后点击开始采集。'); }));
    if (task.source === 'scraper' && runningStates.includes(task.status)) actions.append(taskButton('查看店铺模块',() => { showWorkbenchView('legacy'); loadModules(); }));
  }
}

async function selectTaskRecord(item) {
  const result = await taskJSON(`/api/workbench/records/${encodeURIComponent(item.id)}`);
  renderTaskDetail(result.item);
  document.querySelectorAll('.history-item').forEach(row => row.classList.toggle('selected',row.dataset.recordId === item.id));
}

function renderHistory(items) {
  historyList.replaceChildren();
  if (!items.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = '没有符合条件的任务记录。可以清除筛选或开始新任务。'; historyList.append(empty); return; }
  for (const item of items) {
    const row = document.createElement('div'); row.className = 'history-item'; row.dataset.recordId = item.id;
    row.classList.toggle('selected',selectedTaskRecord?.id === item.id);
    const title = document.createElement('strong'); title.textContent = `${sourceLabel(item.source)} · ${readablePlatform(item.platform)} · ${item.query || '任务'}`;
    const meta = document.createElement('span'); const date = new Date(item.createdAt);
    meta.textContent = `${Number.isNaN(date.valueOf()) ? item.createdAt : date.toLocaleString('zh-CN')} · ${taskStateLabels[item.status] || item.quality?.label || '任务'}${item.counts?.contents ? ` · ${item.counts.contents}条结果` : ''}`;
    const actions = document.createElement('div'); actions.className = 'history-actions';
    actions.append(taskButton('查看详情',() => selectTaskRecord(item)));
    if (item.payload && !runningStates.includes(item.status)) actions.append(taskButton('重试',() => retryTask(item)));
    row.append(title,meta,actions); historyList.append(row);
  }
}

async function retryTask(item) {
  if (item.id.startsWith('task-')) {
    const result = await taskPost(`/api/tasks/${encodeURIComponent(item.id)}/retry`,{requestKey:crypto.randomUUID()});
    showWorkbenchView('history'); renderTaskDetail(result.task); await pollTasks(); await loadHistory(0);
  } else if (item.payload) {
    showWorkbenchView('collect'); applyPayloadToForm(item.payload); await submitTask('collect',item.payload);
  }
}

function historyQuery(page) {
  return new URLSearchParams({page,limit:historyPageSize,source:document.getElementById('historySource').value,search:document.getElementById('historySearch').value.trim(),status:document.getElementById('historyStatus').value,start:document.getElementById('historyStart').value,end:document.getElementById('historyEnd').value});
}

async function loadHistory(page = 0) {
  const generation = ++historyGeneration; historyLoading = true;
  historyPrev.disabled = historyNext.disabled = true;
  try {
    let data = await taskJSON(`/api/workbench/history?${historyQuery(page)}`);
    if (generation !== historyGeneration) return;
    const lastPage = Math.max(0,Math.ceil(data.total / historyPageSize) - 1);
    if (page > lastPage) { page = lastPage; data = await taskJSON(`/api/workbench/history?${historyQuery(page)}`); }
    if (generation !== historyGeneration) return;
    historyPage = page; renderHistory(data.items || []);
    const counts = data.sourceCounts || {};
    document.getElementById('historySources').textContent = Object.entries(counts).filter(([,count]) => count > 0).map(([source,count]) => `${sourceLabel(source)} ${count}`).join(' · ');
    document.getElementById('historyWarnings').textContent = (data.warnings || []).join(' ');
    historyPageInfo.textContent = data.total ? `第${page + 1}/${lastPage + 1}页 · 共${data.total}条` : '没有符合条件的记录';
    historyPrev.disabled = page === 0; historyNext.disabled = page >= lastPage;
  } catch (error) { if (generation === historyGeneration) { historyPageInfo.textContent = error.message; } }
  finally { if (generation === historyGeneration) historyLoading = false; }
}

function renderActiveTasks(items) {
  document.getElementById('activeTasks').classList.toggle('hidden',!items.length);
  const signature = JSON.stringify(items.map(t=>[t.id,t.status,t.stage,t.counts]));
  if (signature === activeListSignature) return;
  activeListSignature = signature;
  const target = document.getElementById('activeTaskList'); target.replaceChildren();
  for (const item of items) {
    const row = document.createElement('div'); row.className = 'active-task-row';
    const description = document.createElement('div'); description.className = 'task-description';
    const title = document.createElement('strong'); title.textContent = `${sourceLabel(item.source)} · ${item.query || '任务'}`;
    const state = document.createElement('span'); state.textContent = `${taskStateLabels[item.status]} · ${item.stage}`;
    description.append(title,state); row.append(description);
    row.append(taskButton('查看任务',async () => { showWorkbenchView('history'); await selectTaskRecord(item); }));
    if (item.status !== 'cancelling') row.append(taskButton('取消',async () => { await taskPost(`/api/tasks/${encodeURIComponent(item.id)}/cancel`); await pollTasks(); }));
    target.append(row);
  }
}

async function pollTasks() {
  if (taskPollBusy) return;
  taskPollBusy = true;
  try {
    const result = await taskJSON('/api/tasks'); activeTaskRecords = result.items || [];
    document.getElementById('taskConnection').textContent = '';
    renderActiveTasks(activeTaskRecords);
    let current = selectedTaskRecord;
    if (!current && activeTaskRecords.length) current = activeTaskRecords.find(t => t.source === (activeWorkbenchView === 'video' ? 'video' : 'collect'));
    if (current?.id.startsWith('task-') && runningStates.includes(current.status)) {
      const next = activeTaskRecords.find(t=>t.id === current.id) || (await taskJSON(`/api/tasks/${encodeURIComponent(current.id)}`)).task;
      if (activeWorkbenchView === 'collect' || activeWorkbenchView === 'history') renderTaskDetail(next);
      else selectedTaskRecord = next;
      if (next.source === 'video') updateVideoTask(next);
      if (!runningStates.includes(next.status)) await loadHistory(historyPage);
    }
  } catch (error) { document.getElementById('taskConnection').textContent = '连接暂时中断，任务记录仍保留。恢复连接后会继续更新。'; }
  finally { taskPollBusy = false; }
}

document.getElementById('checkCollect').addEventListener('click',()=>checkSelectedTask('collect'));
document.getElementById('checkVideo').addEventListener('click',()=>checkSelectedTask('video'));
form.addEventListener('input',()=>document.getElementById('collectPreflight').classList.add('hidden'));
form.addEventListener('change',()=>document.getElementById('collectPreflight').classList.add('hidden'));
document.getElementById('videoUrl').addEventListener('input',()=>document.getElementById('videoPreflight').classList.add('hidden'));
document.getElementById('historyFilters').addEventListener('submit',event=>{event.preventDefault();resetDetail();loadHistory(0);});
document.getElementById('clearHistoryFilters').addEventListener('click',()=>{document.getElementById('historyFilters').reset();document.getElementById('historySource').value='all';resetDetail();loadHistory(0);});
const guideDialog = document.getElementById('guide');
document.getElementById('guideBtn').addEventListener('click',()=>guideDialog.showModal());
document.getElementById('closeGuide').addEventListener('click',()=>guideDialog.close());
document.addEventListener('visibilitychange',()=>{ if (!document.hidden) pollTasks(); });

setTask('taobao');
document.getElementById('localAddress').textContent = `本地地址：${location.host}`;
showWorkbenchView(['collect','history','video','legacy'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'collect');
if (activeWorkbenchView === 'collect') { setStatus('准备采集','填写参数后，先检查条件或直接开始。任务会在后台执行。'); detailSections(false,false,false); }
loadModules(); health(); loadHistory(); loadVideoHelper(); pollTasks();
async function taskPollLoop() { await pollTasks(); setTimeout(taskPollLoop,activeTaskRecords.length || selectedTaskRecord && runningStates.includes(selectedTaskRecord.status) ? 1000 : 5000); }
setTimeout(taskPollLoop,1000);
