const state = {
    activeView: 'overview',
    crawlerPlatform: 'douyin',
    resultTab: 'tasks',
    crawlerPoll: null,
    mediaPoll: null,
    platforms: {},
    mediaPlatforms: {},
    merchantPlatforms: {},
    health: null,
    crawlerInfo: null,
};

const viewMeta = {
    overview: ['总览', '环境状态、最近任务和结果入口。'],
    quick: ['快速抓取', '粘贴链接，提取页面内容或批量抓取。'],
    crawler: ['商品采集', '真机或模拟器上的 App 商品采集流程。'],
    search: ['网页搜索', '电商网页关键词搜索和表格化结果。'],
    competitor: ['竞品采集', '买家视角采集同行商品图片、文案、价格和店铺信息。'],
    video: ['视频下载', '抖音公开视频元数据采集和授权下载。'],
    merchant: ['商家后台', '淘宝卖家、千牛、抖店等登录后后台页面采集。'],
    media: ['媒体采集', 'MediaCrawler 多平台采集任务。'],
    results: ['结果库', '统一查看采集结果、历史记录和输出文件。'],
    settings: ['设置', '环境、路径、会话和设备状态。'],
};

const platformLabels = {
    taobao: '淘宝',
    tmall: '天猫',
    jd: '京东',
    pdd: '拼多多',
    ali1688: '1688',
    douyin: '抖音',
    douyin_mall: '抖音商城',
    kuaishou: '快手',
    kuaishou_mall: '快手商城',
    xiaohongshu: '小红书',
    xhs_mall: '小红书商城',
    bilibili: 'B站',
    weibo: '微博',
    taobao_seller: '淘宝卖家中心',
    qianniu: '千牛',
    doudian: '抖店',
};

const searchablePlatforms = ['taobao', 'tmall', 'jd', 'pdd', 'ali1688', 'douyin_mall', 'kuaishou_mall', 'xhs_mall'];

const taskLabels = {
    app_product: 'App 商品采集',
    media: '媒体采集',
    web_search: '网页搜索',
    quick_scrape: '快速抓取',
    quick_batch: '批量抓取',
    shop_crawl: '店铺采集',
    competitor: '竞品采集',
    video_download: '视频下载',
    merchant: '商家后台',
    crawler: '采集任务',
};

const statusLabels = {
    running: '运行中',
    success: '成功',
    error: '失败',
    stopped: '已停止',
    unknown: '未知',
};

const checkLabels = {
    keyword: '关键词',
    mode: '采集模式',
    platform: '平台',
    venv: 'Python 环境',
    source: '采集源码',
    script: '运行脚本',
    adb: 'ADB',
    device: '设备',
    app: '目标 App',
    output: '输出文件',
};

function $(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function taskShopLabel(row) {
    return row?.shop_name || row?.shop_id || '';
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        headers: options.body ? {'Content-Type': 'application/json'} : undefined,
        ...options,
    });
    const text = await response.text();
    let data = {};
    try {
        data = text ? JSON.parse(text) : {};
    } catch (error) {
        data = {success: false, error: text || error.message};
    }
    if (!response.ok && !data.error) {
        data.error = `${response.status} ${response.statusText}`;
    }
    return data;
}

function showToast(message, type = 'neutral') {
    const toast = $('toast');
    toast.className = `toast show ${type}`;
    toast.textContent = message;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        toast.className = 'toast';
    }, 2600);
}

function statusClass(ok, warn = false) {
    if (ok) return 'ok';
    return warn ? 'warn' : 'bad';
}

function setView(view) {
    state.activeView = view;
    document.querySelectorAll('.view').forEach((el) => el.classList.toggle('active', el.id === `view-${view}`));
    document.querySelectorAll('[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
    const [title, subtitle] = viewMeta[view] || viewMeta.overview;
    $('viewTitle').textContent = title;
    $('viewSubtitle').textContent = subtitle;
    if (view === 'results') loadResultsLibrary();
    if (view === 'settings') loadSettings();
}

function initNavigation() {
    document.querySelectorAll('[data-view]').forEach((button) => {
        button.addEventListener('click', () => setView(button.dataset.view));
    });
    document.querySelectorAll('[data-jump]').forEach((button) => {
        button.addEventListener('click', () => setView(button.dataset.jump));
    });
}

function renderStatusStrip() {
    const healthOk = !!state.health?.ok;
    const adbOk = !!state.health?.checks?.adb?.ok || !!state.crawlerInfo?.adb_ok;
    const deviceOk = !!state.crawlerInfo?.device_running;
    const outputOk = !!state.crawlerInfo?.venv_exists;
    const chips = [
        ['环境', healthOk ? '正常' : '需检查', statusClass(healthOk, true)],
        ['ADB', adbOk ? '可用' : '异常', statusClass(adbOk, true)],
        ['设备', deviceOk ? '已连接' : '未连接', statusClass(deviceOk, true)],
        ['输出目录', outputOk ? '可写' : '需检查', statusClass(outputOk, true)],
    ];
    $('statusStrip').innerHTML = chips
        .map(([name, value, cls]) => `<span class="status-chip ${cls}">${escapeHtml(name)} ${escapeHtml(value)}</span>`)
        .join('');
    $('sideServiceStatus').textContent = healthOk ? '环境正常' : '环境需检查';
}

async function loadHealth() {
    const data = await api('/api/health');
    state.health = data;
    renderHealthGrid('healthGrid', data.checks || {});
    renderHealthGrid('settingsHealth', data.checks || {});
    renderStatusStrip();
    return data;
}

function renderHealthGrid(targetId, checks) {
    const target = $(targetId);
    if (!target) return;
    const names = {
        python: 'Python',
        node: 'Node.js',
        playwright: 'Playwright',
        adb: 'ADB',
        cdp: 'Chrome CDP',
        disk: '磁盘空间',
    };
    const html = Object.entries(checks).map(([key, item]) => {
        const ok = !!item.ok;
        const cls = ok ? 'ok' : 'warn';
        const message = item.version || item.hint || item.error || (item.free_gb ? `${item.free_gb} GB 可用` : (ok ? '正常' : '需处理'));
        return `<div class="health-card ${cls}">
            <strong>${escapeHtml(names[key] || key)}</strong>
            <span>${escapeHtml(message)}</span>
        </div>`;
    }).join('');
    target.innerHTML = html || '<div class="empty">暂无检测结果</div>';
}

async function loadCrawlerInfo() {
    const data = await api('/api/crawler/info');
    state.crawlerInfo = data;
    renderDeviceSelect(data);
    renderDeviceSummary(data);
    renderStatusStrip();
    renderSettingsPaths(data);
    return data;
}

function renderDeviceSelect(data) {
    const select = $('crawlerDeviceSelect');
    const hint = $('crawlerDeviceHint');
    if (!select || !hint) return;
    const previous = select.value;
    const devices = data.devices || [];
    select.innerHTML = '';
    if (!data.adb_ok) {
        select.disabled = true;
        select.innerHTML = '<option value="">ADB 不可用</option>';
        hint.textContent = data.adb_error || '未找到 adb';
        return;
    }
    if (!devices.length) {
        select.disabled = true;
        select.innerHTML = '<option value="">未检测到 Android 设备</option>';
        hint.textContent = `ADB: ${data.adb_path || 'adb'}。请确认手机已开启 USB 调试并允许授权。`;
        return;
    }
    select.disabled = false;
    devices.forEach((device) => {
        const option = document.createElement('option');
        option.value = device.serial;
        option.disabled = device.state !== 'device';
        option.textContent = `${device.is_emulator ? '模拟器' : '真机'} · ${device.label || device.serial} · ${device.state}`;
        select.appendChild(option);
    });
    const preferred = data.selected_device?.serial;
    if (previous && devices.some((device) => device.serial === previous && device.state === 'device')) {
        select.value = previous;
    } else if (preferred) {
        select.value = preferred;
    }
    const ready = devices.filter((device) => device.state === 'device').length;
    hint.textContent = `已检测 ${devices.length} 台，在线 ${ready} 台。`;
}

function renderDeviceSummary(data) {
    const target = $('overviewDeviceSummary');
    if (!target) return;
    const devices = data.devices || [];
    if (!data.adb_ok) {
        target.innerHTML = `<div class="health-card warn"><strong>ADB 异常</strong><span>${escapeHtml(data.adb_error || 'ADB 不可用')}</span></div>`;
        return;
    }
    if (!devices.length) {
        target.innerHTML = `<div class="health-card warn"><strong>未检测到设备</strong><span>${escapeHtml(data.adb_path || 'adb')}</span></div>`;
        return;
    }
    target.innerHTML = devices.map((device) => `<div class="health-card ${device.state === 'device' ? 'ok' : 'warn'}">
        <strong>${escapeHtml(device.is_emulator ? '模拟器' : '真机')} · ${escapeHtml(device.label || device.serial)}</strong>
        <span>${escapeHtml(device.serial)} · ${escapeHtml(device.state)}</span>
    </div>`).join('');
}

async function loadPlatforms() {
    state.platforms = await api('/api/platforms');
    const quick = $('quickPlatform');
    const search = $('searchPlatform');
    const competitor = $('competitorPlatform');
    const platformOptions = Object.entries(state.platforms)
        .map(([key, value]) => `<option value="${escapeHtml(key)}">${escapeHtml(value.name || platformLabels[key] || key)}</option>`)
        .join('');
    quick.innerHTML = `<option value="">自动识别</option>${platformOptions}`;
    search.innerHTML = searchablePlatforms
        .map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(state.platforms[key]?.name || platformLabels[key] || key)}</option>`)
        .join('');
    if (competitor) {
        competitor.innerHTML = searchablePlatforms
            .map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(state.platforms[key]?.name || platformLabels[key] || key)}</option>`)
            .join('');
    }
}

async function loadMediaPlatforms() {
    state.mediaPlatforms = await api('/api/media-crawler/platforms');
    $('mcPlatform').innerHTML = Object.entries(state.mediaPlatforms)
        .map(([key, value]) => `<option value="${escapeHtml(key)}">${escapeHtml(value.name || key)}</option>`)
        .join('');
}

async function loadMerchantPlatforms() {
    state.merchantPlatforms = await api('/api/merchant/platforms');
    const select = $('merchantPlatform');
    if (!select) return;
    select.innerHTML = Object.entries(state.merchantPlatforms)
        .map(([key, value]) => `<option value="${escapeHtml(key)}">${escapeHtml(value.icon || '')} ${escapeHtml(value.name || key)}${value.session_saved ? ' · 已登录' : ''}</option>`)
        .join('');
    renderMerchantDataTypes();
}

function renderMerchantDataTypes() {
    const platform = $('merchantPlatform')?.value;
    const dataTypes = state.merchantPlatforms[platform]?.data_types || {};
    const select = $('merchantDataType');
    if (!select) return;
    select.innerHTML = Object.entries(dataTypes)
        .map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`)
        .join('');
}

async function loadHistory() {
    const data = await api('/api/tasks?limit=20');
    const rows = data.data || [];
    $('recentHistory').innerHTML = rows.slice(0, 6).map((row) => `<div class="compact-row">
        <div class="compact-main">
            <strong>${escapeHtml(taskLabels[row.task_type] || row.task_type || '采集任务')}</strong>
            <br><small>${escapeHtml([taskShopLabel(row), platformLabels[row.platform] || row.platform, row.keyword || row.url || '-'].filter(Boolean).join(' · '))}</small>
        </div>
        <small class="compact-meta">${escapeHtml(formatHistoryTime(row.created_at))} · ${escapeHtml(statusLabels[row.status] || row.status || '')} · ${escapeHtml(row.item_count ?? 0)} 条</small>
    </div>`).join('') || '<div class="empty">暂无历史任务</div>';
    return data;
}

function crawlerPayload(extra = {}) {
    return {
        keyword: $('crawlerKeyword').value.trim(),
        pages: Number($('crawlerPages').value || 3),
        mode: $('crawlerMode').value,
        platform: state.crawlerPlatform,
        serial: $('crawlerDeviceSelect').value || '',
        ...extra,
    };
}

function renderPreflight(data) {
    const checks = data.checks || {};
    const html = Object.entries(checks).map(([key, check]) => {
        const cls = check.ok ? 'ok' : 'warn';
        return `<div class="check-item ${cls}">
            <strong>${escapeHtml(checkLabels[key] || key)}</strong>
            <span>${escapeHtml(check.message || '')}</span>
        </div>`;
    }).join('');
    $('crawlerPreflightBox').innerHTML = html || '<div class="empty">暂无检查结果</div>';
    const ready = !!data.ok;
    $('crawlerReadyState').className = `panel-status ${ready ? 'ok' : 'warn'}`;
    $('crawlerReadyState').textContent = ready ? '可运行' : '需处理';
}

function renderDiagnostics(data) {
    const target = $('crawlerDiagnosticBox');
    if (!target) return;
    const recommendations = data.recommendations || [];
    const errors = data.errors || [];
    const blocks = [
        ...errors.map((message) => ({type: 'warn', message})),
        ...recommendations.map((message) => ({type: data.ok ? 'ok' : 'neutral', message})),
    ];
    target.innerHTML = blocks.map((item) => `<div class="advice-item ${item.type}">
        <i class="fa-solid ${item.type === 'ok' ? 'fa-circle-check' : 'fa-circle-info'}"></i>
        <span>${escapeHtml(item.message)}</span>
    </div>`).join('') || '<div class="empty">暂无处理建议</div>';
}

async function loadCrawlerDiagnostics() {
    const data = await api('/api/crawler/diagnostics', {
        method: 'POST',
        body: JSON.stringify(crawlerPayload({require_device: true})),
    });
    renderDiagnostics(data);
    return data;
}

async function runCrawlerPreflight() {
    const data = await api('/api/crawler/preflight', {
        method: 'POST',
        body: JSON.stringify(crawlerPayload({require_device: true})),
    });
    renderPreflight(data);
    await loadCrawlerDiagnostics();
    showToast(data.ok ? '运行前检查通过' : '运行前检查有阻断项', data.ok ? 'success' : 'warn');
    return data;
}

async function startCrawler() {
    const payload = crawlerPayload();
    if (!payload.keyword) {
        showToast('请输入搜索关键词', 'warn');
        return;
    }
    const data = await api('/api/crawler/run', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (!data.success) {
        if (data.preflight) renderPreflight(data.preflight);
        await loadCrawlerDiagnostics();
        showToast(data.error || '启动失败', 'warn');
        return;
    }
    $('crawlerStartBtn').classList.add('hidden');
    $('crawlerStopBtn').classList.remove('hidden');
    $('crawlerRunState').className = 'panel-status ok';
    $('crawlerRunState').textContent = '运行中';
    $('crawlerLog').textContent = '任务已启动...';
    window.clearInterval(state.crawlerPoll);
    state.crawlerPoll = window.setInterval(pollCrawler, 1800);
    loadHistory();
    showToast('采集已启动', 'success');
}

async function pollCrawler() {
    const data = await api('/api/crawler/status');
    $('crawlerLog').textContent = (data.log || []).slice(-80).join('\n') || '等待日志...';
    if (!data.running) {
        window.clearInterval(state.crawlerPoll);
        $('crawlerStartBtn').classList.remove('hidden');
        $('crawlerStopBtn').classList.add('hidden');
        $('crawlerRunState').className = `panel-status ${data.returncode === 0 ? 'ok' : 'neutral'}`;
        $('crawlerRunState').textContent = data.returncode === 0 ? '已完成' : '空闲';
        loadCrawlerResults(false);
        loadHistory();
    }
}

async function stopCrawler() {
    await api('/api/crawler/stop', {method: 'POST'});
    window.clearInterval(state.crawlerPoll);
    $('crawlerStartBtn').classList.remove('hidden');
    $('crawlerStopBtn').classList.add('hidden');
    $('crawlerRunState').className = 'panel-status warn';
    $('crawlerRunState').textContent = '已停止';
    loadHistory();
    showToast('采集已停止', 'warn');
}

async function loadCrawlerResults(notify = true) {
    const data = await api('/api/crawler/results');
    if (!data.success) {
        $('crawlerResultInfo').textContent = data.error || '暂无结果';
        $('crawlerResultTable').className = 'table-wrap empty';
        $('crawlerResultTable').textContent = '暂无数据';
        if (notify) showToast(data.error || '暂无结果', 'warn');
        return data;
    }
    $('crawlerResultInfo').textContent = `${data.file || ''} · ${data.count || 0} 条`;
    $('crawlerResultTable').className = 'table-wrap';
    renderTable('crawlerResultTable', data.data || [], data.columns);
    return data;
}

async function runQuick(single = true) {
    const raw = $('quickUrl').value.trim();
    if (!raw) {
        showToast('请粘贴链接', 'warn');
        return;
    }
    $('quickResult').className = 'result-surface empty';
    $('quickResult').textContent = '抓取中...';
    const payload = single ? {
        url: raw.split('\n').find(Boolean),
        platform: $('quickPlatform').value,
        use_login: $('quickLogin').checked,
        human_mode: $('quickHuman').checked,
        device: $('quickDevice').value,
    } : {
        urls: raw,
        platform: $('quickPlatform').value,
        use_login: $('quickLogin').checked,
        human_mode: $('quickHuman').checked,
    };
    const data = await api(single ? '/api/scrape' : '/api/scrape/batch', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (!data.success) {
        $('quickResult').className = 'result-surface empty';
        $('quickResult').textContent = data.error || '抓取失败';
        showToast(data.error || '抓取失败', 'warn');
        return;
    }
    $('quickResult').className = 'result-surface';
    renderQuickResult(data, single);
    showToast('抓取完成', 'success');
}

async function previewQuick() {
    const url = $('quickUrl').value.trim().split('\n').find(Boolean);
    if (!url) {
        showToast('请粘贴链接', 'warn');
        return;
    }
    const data = await api('/api/preview', {
        method: 'POST',
        body: JSON.stringify({url, platform: $('quickPlatform').value, device: $('quickDevice').value}),
    });
    $('quickResult').className = 'result-surface';
    $('quickResult').innerHTML = `<div class="key-value-grid">
        <div class="kv-item"><strong>${escapeHtml(data.title || '预览')}</strong><code>${escapeHtml(data.preview || data.error || '')}</code></div>
    </div>`;
}

function renderQuickResult(data, single) {
    if (!single) {
        const rows = (data.results || []).map((item) => ({
            url: item.url,
            platform: item.platform,
            status: item.success ? '成功' : '失败',
            count: Array.isArray(item.data) ? item.data.length : '',
            error: item.error || '',
        }));
        renderTable('quickResult', rows);
        return;
    }
    const rows = (data.results || []).map((item) => ({
        字段: item.name || item.key,
        数量: item.count,
        来源: item.source || '',
        内容: (item.items || []).slice(0, 3).join('\n'),
    }));
    if (rows.length) {
        renderTable('quickResult', rows);
    } else {
        $('quickResult').innerHTML = '<div class="empty">未提取到结构化结果</div>';
    }
}

async function runSearch() {
    const keyword = $('searchKeyword').value.trim();
    if (!keyword) {
        showToast('请输入关键词', 'warn');
        return;
    }
    $('searchResult').className = 'table-wrap empty';
    $('searchResult').textContent = '搜索中...';
    const data = await api('/api/search', {
        method: 'POST',
        body: JSON.stringify({
            platform: $('searchPlatform').value,
            keyword,
            pages: Number($('searchPages').value || 1),
            human_mode: $('searchHuman').checked,
        }),
    });
    if (!data.success) {
        $('searchSummary').textContent = data.error || '搜索失败';
        $('searchResult').textContent = data.error || '搜索失败';
        showToast(data.error || '搜索失败', 'warn');
        return;
    }
    $('searchSummary').textContent = `${data.platform || ''} · ${data.total || 0} 条`;
    $('searchResult').className = 'table-wrap';
    renderTable('searchResult', data.items || []);
}

function renderCompetitorTable(rows) {
    const target = $('competitorResult');
    if (!target) return;
    if (!rows || !rows.length) {
        target.className = 'table-wrap empty';
        target.textContent = '暂无数据';
        return;
    }
    target.className = 'table-wrap';
    const body = rows.slice(0, 120).map((row) => {
        const image = row.main_image || (Array.isArray(row.images) ? row.images[0] : '');
        const title = row.title || '-';
        const copy = row.copy || '';
        const link = row.link || '';
        return `<tr>
            <td>${image ? `<img class="product-thumb" src="${escapeHtml(image)}" alt="">` : '-'}</td>
            <td title="${escapeHtml(title)}">${escapeHtml(title.length > 80 ? title.slice(0, 80) + '...' : title)}</td>
            <td>${escapeHtml(row.price || '-')}</td>
            <td>${escapeHtml(row.shop || '-')}</td>
            <td>${escapeHtml(row.sales || row.rating || '-')}</td>
            <td title="${escapeHtml(copy)}">${escapeHtml(copy.length > 120 ? copy.slice(0, 120) + '...' : copy || '-')}</td>
            <td>${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">打开</a>` : '-'}</td>
        </tr>`;
    }).join('');
    target.innerHTML = `<table>
        <thead><tr><th>图</th><th>标题/卖点</th><th>价格</th><th>店铺</th><th>销量/评价</th><th>文案</th><th>链接</th></tr></thead>
        <tbody>${body}</tbody>
    </table>`;
}

async function runCompetitor() {
    const keyword = $('competitorKeyword').value.trim();
    const urls = $('competitorUrls').value.trim();
    if (!keyword && !urls) {
        showToast('请输入关键词或商品链接', 'warn');
        return;
    }
    $('competitorSummary').textContent = '采集中...';
    $('competitorResult').className = 'table-wrap empty';
    $('competitorResult').textContent = '采集中...';
    const data = await api('/api/competitor/run', {
        method: 'POST',
        body: JSON.stringify({
            platform: $('competitorPlatform').value,
            keyword,
            urls,
            pages: Number($('competitorPages').value || 1),
            human_mode: $('competitorHuman').checked,
            fetch_details: $('competitorFetchDetails').checked,
        }),
    });
    if (!data.success) {
        $('competitorSummary').textContent = data.error || '采集失败';
        $('competitorResult').className = 'table-wrap empty';
        $('competitorResult').textContent = data.error || '采集失败';
        showToast(data.error || '竞品采集失败', 'warn');
        loadHistory();
        return;
    }
    $('competitorSummary').textContent = `${data.platform || ''} · ${data.keyword || '商品链接'} · ${data.count || 0} 条`;
    renderCompetitorTable(data.items || []);
    loadHistory();
    showToast('竞品采集完成', 'success');
}

function renderVideoTable(rows) {
    const target = $('videoResult');
    if (!target) return;
    if (!rows || !rows.length) {
        target.className = 'table-wrap empty';
        target.textContent = '暂无数据';
        return;
    }
    target.className = 'table-wrap';
    const body = rows.map((row) => {
        const cover = row.cover || '';
        const title = row.title || '-';
        const files = Array.isArray(row.downloaded_files) ? row.downloaded_files.join('\n') : '';
        const sourceUrl = row.page_url || row.source_url || '';
        const error = row.download_error || row.metadata_error || '';
        return `<tr>
            <td>${cover ? `<img class="product-thumb" src="${escapeHtml(cover)}" alt="">` : '-'}</td>
            <td title="${escapeHtml(title)}">${escapeHtml(title.length > 80 ? title.slice(0, 80) + '...' : title)}</td>
            <td>${escapeHtml(row.author || '-')}</td>
            <td>${escapeHtml(row.status || '-')}</td>
            <td title="${escapeHtml(files || error)}">${escapeHtml((files || error || '-').slice(0, 140))}</td>
            <td>${sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">来源</a>` : '-'}</td>
        </tr>`;
    }).join('');
    target.innerHTML = `<table>
        <thead><tr><th>封面</th><th>标题</th><th>作者</th><th>状态</th><th>文件/错误</th><th>链接</th></tr></thead>
        <tbody>${body}</tbody>
    </table>`;
}

async function runVideoDownload() {
    const urls = $('videoUrls').value.trim();
    const downloadFile = $('videoDownloadFile').checked;
    const confirmRights = $('videoConfirmRights').checked;
    if (!urls) {
        showToast('请粘贴抖音视频链接', 'warn');
        return;
    }
    if (downloadFile && !confirmRights) {
        showToast('下载前请先确认你有权保存这些视频', 'warn');
        return;
    }
    $('videoSummary').textContent = '处理中...';
    $('videoResult').className = 'table-wrap empty';
    $('videoResult').textContent = '处理中...';
    const data = await api('/api/video-download/run', {
        method: 'POST',
        body: JSON.stringify({
            platform: 'douyin',
            urls,
            download_file: downloadFile,
            confirm_rights: confirmRights,
            human_mode: $('videoHuman').checked,
        }),
    });
    renderVideoTable(data.items || []);
    if (!data.success) {
        $('videoSummary').textContent = data.error || (data.errors || []).slice(0, 1).join('') || '处理失败';
        showToast(data.error || '视频处理失败', 'warn');
        loadHistory();
        return;
    }
    const toolState = data.ytdlp_available ? 'yt-dlp 可用' : '未检测到 yt-dlp';
    $('videoSummary').textContent = `${data.count || 0} 条成功 · ${toolState}${data.download_dir ? ` · ${data.download_dir}` : ''}`;
    loadHistory();
    showToast('视频处理完成', 'success');
}

function merchantPayload() {
    return {
        platform: $('merchantPlatform').value,
        data_type: $('merchantDataType').value,
        shop_name: $('merchantShopName')?.value.trim() || '',
        shop_id: $('merchantShopId')?.value.trim() || '',
        url: $('merchantUrl').value.trim(),
        wait_seconds: Number($('merchantWaitSeconds').value || 8),
        human_mode: $('merchantRunMode').value === 'visible',
    };
}

function renderMerchantDiagnostics(data) {
    const target = $('merchantDiagnosticBox');
    if (!target) return;
    const checks = data.checks || {};
    const checkHtml = Object.entries(checks).map(([key, check]) => `<div class="check-item ${check.ok ? 'ok' : 'warn'}">
        <strong>${escapeHtml(key)}</strong>
        <span>${escapeHtml(check.message || '')}</span>
    </div>`).join('');
    const adviceHtml = (data.recommendations || []).map((message) => `<div class="advice-item neutral">
        <i class="fa-solid fa-circle-info"></i><span>${escapeHtml(message)}</span>
    </div>`).join('');
    target.innerHTML = checkHtml + adviceHtml || '<div class="empty">暂无诊断结果</div>';
    $('merchantSummary').textContent = data.ok ? '条件可运行' : '需要处理阻断项';
}

async function runMerchantDiagnostics(notify = true) {
    const data = await api('/api/merchant/diagnostics', {
        method: 'POST',
        body: JSON.stringify(merchantPayload()),
    });
    renderMerchantDiagnostics(data);
    if (notify) {
        showToast(data.ok ? '商家后台检查通过' : '商家后台检查有阻断项', data.ok ? 'success' : 'warn');
    }
    return data;
}

async function loginMerchant() {
    const platform = $('merchantPlatform').value;
    showToast('将打开浏览器，请登录后等待会话保存', 'warn');
    const data = await api('/api/login', {
        method: 'POST',
        body: JSON.stringify({platform}),
    });
    if (!data.success) {
        showToast(data.error || '登录态保存失败', 'warn');
        return;
    }
    await loadMerchantPlatforms();
    await runMerchantDiagnostics(false);
    showToast('登录态已保存', 'success');
}

async function runMerchant() {
    const diagnostics = await runMerchantDiagnostics(false);
    if (!diagnostics.ok) {
        showToast('请先处理商家后台阻断项', 'warn');
        return;
    }
    $('merchantResultInfo').textContent = '采集中...';
    $('merchantResultTable').className = 'table-wrap empty';
    $('merchantResultTable').textContent = '采集中...';
    const data = await api('/api/merchant/run', {
        method: 'POST',
        body: JSON.stringify(merchantPayload()),
    });
    if (!data.success) {
        if (data.diagnostics) renderMerchantDiagnostics(data.diagnostics);
        $('merchantResultInfo').textContent = data.error || '采集失败';
        $('merchantResultTable').className = 'table-wrap empty';
        $('merchantResultTable').textContent = data.error || '采集失败';
        showToast(data.error || '商家后台采集失败', 'warn');
        loadHistory();
        return;
    }
    $('merchantResultInfo').textContent = [data.platform || '', data.shop_name || data.shop_id || '', data.title || '', `${data.count || 0} 条`].filter(Boolean).join(' · ');
    $('merchantResultTable').className = 'table-wrap';
    renderTable('merchantResultTable', data.records || []);
    loadHistory();
    showToast('商家后台采集完成', 'success');
}

async function startMedia() {
    const keyword = $('mcKeyword').value.trim();
    if (!keyword) {
        showToast('请输入关键词或 ID', 'warn');
        return;
    }
    const data = await api('/api/media-crawler/run', {
        method: 'POST',
        body: JSON.stringify({
            platform: $('mcPlatform').value,
            keyword,
            type: $('mcType').value,
            login_type: $('mcLoginType').value,
            pages: Number($('mcPages').value || 5),
        }),
    });
    if (!data.success) {
        showToast(data.error || '启动失败', 'warn');
        return;
    }
    $('mcStartBtn').classList.add('hidden');
    $('mcStopBtn').classList.remove('hidden');
    $('mcLog').textContent = 'MediaCrawler 已启动...';
    window.clearInterval(state.mediaPoll);
    state.mediaPoll = window.setInterval(pollMedia, 1800);
    loadHistory();
    showToast('MediaCrawler 已启动', 'success');
}

async function pollMedia() {
    const data = await api('/api/media-crawler/status');
    $('mcLog').textContent = (data.log || []).slice(-80).join('\n') || '等待日志...';
    if (!data.running) {
        window.clearInterval(state.mediaPoll);
        $('mcStartBtn').classList.remove('hidden');
        $('mcStopBtn').classList.add('hidden');
        loadMediaResults(false);
        loadHistory();
    }
}

async function stopMedia() {
    await api('/api/media-crawler/stop', {method: 'POST'});
    window.clearInterval(state.mediaPoll);
    $('mcStartBtn').classList.remove('hidden');
    $('mcStopBtn').classList.add('hidden');
    loadHistory();
    showToast('MediaCrawler 已停止', 'warn');
}

async function loadMediaResults(notify = true) {
    const data = await api('/api/media-crawler/results');
    if (!data.success && !data.files) {
        $('mcResultTable').className = 'table-wrap compact empty';
        $('mcResultTable').textContent = data.error || '暂无结果';
        if (notify) showToast(data.error || '暂无结果', 'warn');
        return data;
    }
    $('mcResultTable').className = 'table-wrap compact';
    renderTable('mcResultTable', data.data || data.files || [], data.columns);
    return data;
}

function renderTable(targetId, rows, explicitColumns) {
    const target = $(targetId);
    if (!target) return;
    if (!rows || !rows.length) {
        target.classList.add('empty');
        target.textContent = '暂无数据';
        return;
    }
    target.classList.remove('empty');
    const columns = explicitColumns && explicitColumns.length ? explicitColumns : Object.keys(rows[0]);
    const header = columns.map((col) => `<th>${escapeHtml(col)}</th>`).join('');
    const body = rows.slice(0, 120).map((row) => `<tr>${columns.map((col) => {
        const value = row[col] ?? '';
        const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
        return `<td title="${escapeHtml(text)}">${escapeHtml(text.length > 220 ? text.slice(0, 220) + '...' : text)}</td>`;
    }).join('')}</tr>`).join('');
    target.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

function taskStatusClass(status) {
    if (status === 'success') return 'ok';
    if (status === 'running') return 'running';
    if (status === 'error') return 'bad';
    if (status === 'stopped') return 'warn';
    return 'neutral';
}

async function loadTaskCenter() {
    const data = await api('/api/tasks?limit=120');
    const rows = data.data || [];
    const target = $('resultLibrary');
    if (!rows.length) {
        target.className = 'table-wrap empty';
        target.textContent = '暂无任务';
        return data;
    }
    target.className = 'table-wrap';
    const body = rows.map((row) => {
        const title = row.keyword || row.url || row.output_file || '-';
        const shop = taskShopLabel(row) || '-';
        const output = row.output_file || row.error || '';
        return `<tr>
            <td>${escapeHtml(formatHistoryTime(row.created_at))}</td>
            <td>${escapeHtml(taskLabels[row.task_type] || row.task_type || '采集任务')}</td>
            <td>${escapeHtml(platformLabels[row.platform] || row.platform || '-')}</td>
            <td>${escapeHtml(shop)}</td>
            <td title="${escapeHtml(title)}">${escapeHtml(title.length > 80 ? title.slice(0, 80) + '...' : title)}</td>
            <td>${escapeHtml(row.mode || '-')}</td>
            <td><span class="task-status ${taskStatusClass(row.status)}">${escapeHtml(statusLabels[row.status] || row.status || '-')}</span></td>
            <td>${escapeHtml(row.item_count ?? 0)}</td>
            <td title="${escapeHtml(output)}">${escapeHtml(output.length > 100 ? output.slice(0, 100) + '...' : output)}</td>
        </tr>`;
    }).join('');
    target.innerHTML = `<table>
        <thead><tr><th>时间</th><th>任务</th><th>平台</th><th>店铺</th><th>关键词/链接</th><th>模式</th><th>状态</th><th>条数</th><th>输出/错误</th></tr></thead>
        <tbody>${body}</tbody>
    </table>`;
    return data;
}

async function loadResultsLibrary() {
    if (state.resultTab === 'tasks') {
        await loadTaskCenter();
    } else if (state.resultTab === 'crawler') {
        const data = await loadCrawlerResults(false);
        const files = data.files || [];
        renderTable('resultLibrary', files.map((file) => ({
            文件: file.name,
            行数: file.rows ?? '',
            大小: formatBytes(file.size || 0),
            更新时间: formatTime(file.mtime),
            路径: file.path,
        })));
    } else if (state.resultTab === 'media') {
        const data = await loadMediaResults(false);
        const files = data.files || [];
        renderTable('resultLibrary', files.map((file) => ({
            文件: file.name,
            大小: formatBytes(file.size || 0),
            更新时间: formatTime(file.mtime),
            路径: file.path,
        })));
    } else {
        const data = await api('/api/history?limit=80');
        renderTable('resultLibrary', (data.data || []).map((row) => ({
            时间: (row.created_at || '').slice(0, 19).replace('T', ' '),
            平台: row.platform,
            店铺: taskShopLabel(row),
            关键词: row.keyword,
            链接: row.url,
            模式: row.mode,
            条数: row.item_count,
            状态: row.status,
        })));
    }
}

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(value) {
    if (!value) return '';
    const date = new Date(value * 1000);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('zh-CN', {hour12: false});
}

function formatHistoryTime(value) {
    if (!value) return '';
    const normalized = String(value).replace('T', ' ');
    return normalized.length >= 16 ? normalized.slice(5, 16) : normalized;
}

async function loadSettings() {
    await Promise.allSettled([loadHealth(), loadCrawlerInfo(), loadSessions()]);
}

function renderSettingsPaths(data) {
    const target = $('settingsPaths');
    if (!target) return;
    const rows = [
        ['项目目录', data.project_dir || ''],
        ['ADB 路径', data.adb_path || ''],
        ['UI 脚本', data.scripts?.run_ui || ''],
        ['API 脚本', data.scripts?.run_api || ''],
    ];
    target.innerHTML = rows.map(([name, value]) => `<div class="path-row"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(value)}</span></div>`).join('');
}

async function loadSessions() {
    const data = await api('/api/sessions');
    const sessions = data.sessions || [];
    $('sessionList').innerHTML = sessions.map((session) => `<div class="path-row">
        <strong>${escapeHtml(session.name || session.platform)}</strong>
        <span>${escapeHtml(session.path || '')}</span>
    </div>`).join('') || '<div class="path-row"><strong>登录会话</strong><span>暂无保存会话</span></div>';
}

function initEvents() {
    $('refreshHealthBtn').addEventListener('click', loadHealth);
    $('settingsRefreshBtn').addEventListener('click', loadSettings);
    $('refreshDevicesBtn').addEventListener('click', loadCrawlerInfo);
    $('crawlerDeviceRefresh').addEventListener('click', loadCrawlerInfo);

    document.querySelectorAll('#crawlerPlatformSelector button').forEach((button) => {
        button.addEventListener('click', () => {
            state.crawlerPlatform = button.dataset.platform;
            document.querySelectorAll('#crawlerPlatformSelector button').forEach((el) => el.classList.toggle('selected', el === button));
        });
    });

    $('crawlerPreflightBtn').addEventListener('click', runCrawlerPreflight);
    $('crawlerStartBtn').addEventListener('click', startCrawler);
    $('crawlerStopBtn').addEventListener('click', stopCrawler);
    $('crawlerResultsBtn').addEventListener('click', () => loadCrawlerResults(true));

    $('quickRunBtn').addEventListener('click', () => runQuick(true));
    $('quickBatchBtn').addEventListener('click', () => runQuick(false));
    $('quickPreviewBtn').addEventListener('click', previewQuick);
    $('quickClearBtn').addEventListener('click', () => {
        $('quickResult').className = 'result-surface empty';
        $('quickResult').textContent = '等待抓取结果';
    });

    $('searchRunBtn').addEventListener('click', runSearch);
    $('competitorRunBtn').addEventListener('click', runCompetitor);
    $('videoRunBtn').addEventListener('click', runVideoDownload);
    $('merchantPlatform').addEventListener('change', () => {
        renderMerchantDataTypes();
        runMerchantDiagnostics(false);
    });
    $('merchantDataType').addEventListener('change', () => runMerchantDiagnostics(false));
    $('merchantRunMode').addEventListener('change', () => runMerchantDiagnostics(false));
    $('merchantLoginBtn').addEventListener('click', loginMerchant);
    $('merchantDiagnosticBtn').addEventListener('click', () => runMerchantDiagnostics(true));
    $('merchantRunBtn').addEventListener('click', runMerchant);
    $('mcStartBtn').addEventListener('click', startMedia);
    $('mcStopBtn').addEventListener('click', stopMedia);
    $('mcResultsBtn').addEventListener('click', () => loadMediaResults(true));
    $('refreshResultsBtn').addEventListener('click', loadResultsLibrary);

    document.querySelectorAll('[data-result-tab]').forEach((button) => {
        button.addEventListener('click', () => {
            state.resultTab = button.dataset.resultTab;
            document.querySelectorAll('[data-result-tab]').forEach((el) => el.classList.toggle('selected', el === button));
            loadResultsLibrary();
        });
    });
}

async function bootstrap() {
    initNavigation();
    initEvents();
    await Promise.allSettled([
        loadPlatforms(),
        loadMediaPlatforms(),
        loadMerchantPlatforms(),
        loadHealth(),
        loadCrawlerInfo(),
        loadHistory(),
    ]);
    renderStatusStrip();
}

document.addEventListener('DOMContentLoaded', () => {
    const requestedView = new URLSearchParams(location.search).get('view');
    if (['competitor', 'merchant', 'media', 'results', 'settings'].includes(requestedView)) setView(requestedView);
    bootstrap().catch((error) => {
        console.error(error);
        showToast(error.message || '初始化失败', 'bad');
    });
});
