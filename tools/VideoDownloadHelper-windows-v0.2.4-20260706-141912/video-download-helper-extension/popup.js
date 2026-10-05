const pageMeta = document.getElementById("page-meta");
const itemCount = document.getElementById("item-count");
const jobCount = document.getElementById("job-count");
const jobsContainer = document.getElementById("jobs");
const recentDownloadsContainer = document.getElementById("recent-downloads");
const featuredContainer = document.getElementById("featured");
const itemsContainer = document.getElementById("items");
const primaryOnlyToggle = document.getElementById("primary-only-toggle");
const filterMeta = document.getElementById("filter-meta");
const autoProbeUrls = new Set();
const PRIMARY_ONLY_STORAGE_KEY = "videoGrab.primaryOnly";

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function formatBytes(value) {
  if (!value || !Number.isFinite(value)) {
    return "未知大小";
  }
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let current = value;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current.toFixed(current >= 100 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(value) {
  if (!value || !Number.isFinite(value)) {
    return "未知时长";
  }
  const totalSeconds = Math.round(value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const hours = Math.floor(minutes / 60);
  if (hours > 0) {
    return `${hours}:${String(minutes % 60).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function shortUrl(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`.slice(0, 90);
  } catch (_error) {
    return url.slice(0, 90);
  }
}

function compactPath(path) {
  const text = normalizeLabel(path);
  if (!text) {
    return "";
  }
  const parts = text.split(/[\\/]/).filter(Boolean);
  if (!parts.length) {
    return truncateText(text, 54);
  }
  if (parts.length === 1) {
    return truncateText(parts[0], 54);
  }
  return truncateText(`.../${parts.slice(-2).join("/")}`, 54);
}

function formatPageMeta(url) {
  try {
    const parsed = new URL(url);
    const readablePath = decodeURIComponent(parsed.pathname || "/").replace(/\/+$/, "") || "/";
    const queryText = normalizeLabel(
      parsed.searchParams.get("keyword") ||
      parsed.searchParams.get("q") ||
      ""
    );
    const base = `${parsed.hostname}${readablePath}`;
    if (queryText) {
      return truncateText(`${base} · ${queryText}`, 72);
    }
    return truncateText(base, 72);
  } catch (_error) {
    return truncateText(url, 72);
  }
}

function truncateText(value, maxLength = 42) {
  const text = normalizeLabel(value);
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function getUrlMeta(url) {
  try {
    const parsed = new URL(url);
    const compactPath = parsed.pathname
      .split("/")
      .filter(Boolean)
      .slice(-3)
      .join("/");
    return {
      host: parsed.hostname,
      path: compactPath || parsed.pathname || "/"
    };
  } catch (_error) {
    return {
      host: "",
      path: truncateText(url, 48)
    };
  }
}

function getItemHeadline(item) {
  return truncateText(item.videoTitle || item.title || "", 34) || truncateText(shortUrl(item.url), 34);
}

function getItemSubline(item) {
  const meta = getUrlMeta(item.url);
  if (meta.host && meta.path) {
    return `${meta.host} · ${meta.path}`;
  }
  return meta.host || meta.path || "";
}

function normalizeLabel(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function formatPublishDate(value) {
  const text = normalizeLabel(value);
  if (!text) {
    return "";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text;
  }
  if (/^\d{2}-\d{2}$/.test(text)) {
    return text;
  }
  return text;
}

function getAuthorDateLabel(item) {
  const authorName = normalizeLabel(item.authorName);
  const publishDate = formatPublishDate(item.publishDate);
  if (authorName && publishDate) {
    return `${authorName} · ${publishDate}`;
  }
  return authorName || publishDate || "";
}

function extractQueryValue(url, key) {
  try {
    const parsed = new URL(url);
    return parsed.searchParams.get(key) || "";
  } catch (_error) {
    return "";
  }
}

function getPathMarker(url, marker) {
  try {
    const parts = new URL(url).pathname.split("/").filter(Boolean);
    const index = parts.indexOf(marker);
    return index > 0 ? parts[index - 1] : "";
  } catch (_error) {
    return "";
  }
}

function belongsToSameMediaFamily(item, anchor) {
  if (!item || !anchor) {
    return false;
  }
  if (item.url === anchor.url) {
    return true;
  }

  const itemPathToken = getPathMarker(item.url, "video");
  const anchorPathToken = getPathMarker(anchor.url, "video");
  if (itemPathToken && anchorPathToken && itemPathToken === anchorPathToken) {
    return true;
  }

  const itemL = extractQueryValue(item.url, "l");
  const anchorL = extractQueryValue(anchor.url, "l");
  if (itemL && anchorL && itemL === anchorL) {
    return true;
  }

  const itemDyQ = extractQueryValue(item.url, "dy_q");
  const anchorDyQ = extractQueryValue(anchor.url, "dy_q");
  if (itemDyQ && anchorDyQ && itemDyQ === anchorDyQ) {
    return true;
  }

  const itemAuthorDate = `${normalizeLabel(item.authorName)}|${formatPublishDate(item.publishDate)}`;
  const anchorAuthorDate = `${normalizeLabel(anchor.authorName)}|${formatPublishDate(anchor.publishDate)}`;
  if (itemAuthorDate !== "|" && itemAuthorDate === anchorAuthorDate) {
    const itemDuration = Number(item.duration || 0);
    const anchorDuration = Number(anchor.duration || 0);
    if (!itemDuration || !anchorDuration || Math.abs(itemDuration - anchorDuration) <= 2.5) {
      return true;
    }
  }

  return false;
}

function isLikelyFragment(item) {
  const size = Number(item.contentLength || 0);
  return (
    item.kind === "segment" ||
    (item.kind === "video" &&
      !item.duration &&
      size > 0 &&
      size < 1024 * 1024)
  );
}

function analyzeUrl(url) {
  const lowered = String(url || "").toLowerCase();
  return {
    isDecorativeAsset: (
      lowered.includes("/logo/") ||
      lowered.includes("/cover/") ||
      lowered.includes("/poster/") ||
      lowered.includes("/preview/") ||
      lowered.includes("/watermark/") ||
      lowered.includes("/avatar/") ||
      lowered.includes("/sprite/") ||
      lowered.includes("/image/") ||
      lowered.includes("/img/")
    ),
    isDouyinVod: lowered.includes("douyinvod.com"),
    isDirectVideoFile: /\.(mp4|webm|mov|m4v)(?:$|\?)/i.test(lowered)
  };
}

function scoreItem(item) {
  let score = 0;
  const size = Number(item.contentLength || 0);
  const url = String(item.url || "").toLowerCase();
  const { isDecorativeAsset, isDouyinVod, isDirectVideoFile } = analyzeUrl(url);

  if (item.kind === "m3u8") {
    score += 300;
  }
  if (item.source === "api") {
    score += 220;
  }
  if (item.source === "dom") {
    score += 180;
  }
  if (item.source === "network") {
    score += 80;
  }
  if (item.duration && Number.isFinite(item.duration)) {
    score += 240 + Math.min(180, Math.round(item.duration));
  }
  if (!item.duration && size >= 2 * 1024 * 1024) {
    score += 120;
  }
  if (size > 0) {
    score += Math.min(220, Math.round(size / (1024 * 1024) * 30));
  }
  if (item.contentType === "video/mp4") {
    score += 40;
  }
  if (isDouyinVod) {
    score += 25;
  }
  if (isDirectVideoFile) {
    score += 15;
  }
  if (item.width && item.height) {
    if (item.height >= 1000) {
      score += 30;
    }
    if (item.height > item.width) {
      score += 15;
    }
  }
  if (item.duration && item.duration >= 20) {
    score += 90;
  }
  if (item.duration && item.duration < 8) {
    score -= 320;
  } else if (item.duration && item.duration < 15) {
    score -= 160;
  }
  if (isDecorativeAsset) {
    score -= 520;
  }
  if (isLikelyFragment(item)) {
    score -= 260;
  }

  return score;
}

function getCurrentVideoMatchScore(item, activeVideo) {
  if (!activeVideo) {
    return 0;
  }

  let score = 0;
  const itemDuration = Number(item.duration || 0);
  const activeDuration = Number(activeVideo.duration || 0);

  if (itemDuration > 0 && activeDuration > 0) {
    const durationDiff = Math.abs(itemDuration - activeDuration);
    if (durationDiff <= 1.5) {
      score += 320;
    } else if (durationDiff <= 4) {
      score += 160;
    } else if (durationDiff >= 12) {
      score -= 180;
    }
  }

  if (item.width && item.height && activeVideo.width && activeVideo.height) {
    if (item.width === activeVideo.width && item.height === activeVideo.height) {
      score += 120;
    } else if (Math.abs(item.width - activeVideo.width) <= 16 && Math.abs(item.height - activeVideo.height) <= 16) {
      score += 90;
    } else {
      score -= 80;
    }
  }

  if (activeVideo.intersectionRatio && activeVideo.intersectionRatio > 0.5) {
    score += 30;
  }

  return score;
}

function isCurrentVideoCandidate(item, activeVideo) {
  return getCurrentVideoMatchScore(item, activeVideo) >= 180;
}

function sortItems(items, activeVideo = null) {
  return [...items].sort((a, b) => {
    const currentDiff = getCurrentVideoMatchScore(b, activeVideo) - getCurrentVideoMatchScore(a, activeVideo);
    if (currentDiff !== 0) {
      return currentDiff;
    }
    return scoreItem(b) - scoreItem(a);
  });
}

function getThumbnailSrc(item) {
  return item.thumbnailDataUrl || item.thumbnailUrl || "";
}

function canCompleteDownload(item) {
  const url = String(item.url || "").toLowerCase();
  const contentType = String(item.contentType || "").toLowerCase();
  return (
    item.kind !== "segment" &&
    item.kind !== "audio" &&
    !analyzeUrl(url).isDecorativeAsset &&
    (
      contentType.startsWith("video/") ||
      analyzeUrl(url).isDirectVideoFile ||
      url.includes("media-video-avc1") ||
      url.includes("mime_type=video_mp4")
    )
  );
}

function getRecommendedItem(items) {
  if (!items.length) {
    return null;
  }
  return sortItems(items.filter(isPrimaryCandidate), currentActiveVideoHint)[0] || sortItems(items, currentActiveVideoHint)[0] || null;
}

function getCurrentVideoFamily(items, activeVideo) {
  if (!activeVideo) {
    return [];
  }
  const currentCandidates = sortItems(
    items.filter((item) => isCurrentVideoCandidate(item, activeVideo)),
    activeVideo
  );
  const anchor = currentCandidates[0] || null;
  if (!anchor) {
    return [];
  }
  return sortItems(items.filter((item) => belongsToSameMediaFamily(item, anchor)), activeVideo);
}

function isPrimaryCandidate(item) {
  const size = Number(item.contentLength || 0);
  const urlInfo = analyzeUrl(item.url);

  if (item.kind === "segment" || item.kind === "audio") {
    return false;
  }
  if (urlInfo.isDecorativeAsset) {
    return false;
  }
  if (isLikelyFragment(item)) {
    return false;
  }
  if (item.duration && item.duration >= 15) {
    return true;
  }
  if (item.width && item.height && item.height >= 960 && item.height > item.width) {
    return true;
  }
  if (size >= 2 * 1024 * 1024 && (item.source === "api" || item.source === "dom" || urlInfo.isDouyinVod)) {
    return true;
  }
  if (item.kind === "m3u8") {
    return true;
  }
  return scoreItem(item) >= 240;
}

function getPrimaryOnlyEnabled() {
  const saved = localStorage.getItem(PRIMARY_ONLY_STORAGE_KEY);
  return saved == null ? true : saved === "true";
}

function setPrimaryOnlyEnabled(enabled) {
  localStorage.setItem(PRIMARY_ONLY_STORAGE_KEY, enabled ? "true" : "false");
}

const urlParams = new URLSearchParams(window.location.search);
const forcedTabId = Number.parseInt(urlParams.get("tabId") || "", 10);
const forcedPageUrl = urlParams.get("pageUrl") || "";
let currentActiveVideoHint = null;

async function getState() {
  return await chrome.runtime.sendMessage({
    target: "background",
    action: "GET_ACTIVE_TAB_STATE",
    tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
    pageUrl: forcedPageUrl || undefined
  });
}

async function refreshState() {
  const response = await getState();
  const state = response.state;
  currentActiveVideoHint = state.pageContext && state.pageContext.activeVideo ? state.pageContext.activeVideo : null;
  const sortedItems = sortItems(state.items, currentActiveVideoHint);
  const primaryItems = sortedItems.filter(isPrimaryCandidate);
  const currentItems = getCurrentVideoFamily(sortedItems, currentActiveVideoHint);
  const primaryOnlyEnabled = primaryOnlyToggle.checked;
  const visibleItems = primaryOnlyEnabled
    ? (currentItems.length ? currentItems : primaryItems)
    : sortedItems;
  const recommendedItem = getRecommendedItem(sortedItems);

  pageMeta.textContent = response.url ? formatPageMeta(response.url) : "未检测到活动页面";
  itemCount.textContent = String(visibleItems.length);
  jobCount.textContent = String(state.jobs.length);
  filterMeta.textContent = primaryOnlyEnabled
    ? `当前锁定 ${visibleItems.length} 条同组资源，共抓到 ${sortedItems.length} 条`
    : `当前显示全部 ${sortedItems.length} 条，包含 logo、预览、碎片等杂项`;

  renderJobs(state.jobs);
  renderRecentDownloads(response.recentDownloads || []);
  renderFeatured(recommendedItem);
  renderItems(visibleItems, primaryOnlyEnabled, recommendedItem);
  void maybeAutoProbe(sortedItems);
}

async function maybeAutoProbe(items) {
  const targets = items
    .filter((item) =>
      item.kind === "video" &&
      (item.source === "network" || item.source === "dom" || item.source === "api") &&
      (String(item.contentType || "").startsWith("video/") || /\.(mp4|webm|mov|m4v)(?:$|\?)/i.test(item.url)) &&
      !analyzeUrl(item.url).isDecorativeAsset &&
      (!item.duration || !getThumbnailSrc(item)) &&
      !autoProbeUrls.has(item.url)
    )
    .sort((a, b) => {
      const currentDiff = getCurrentVideoMatchScore(b, currentActiveVideoHint) - getCurrentVideoMatchScore(a, currentActiveVideoHint);
      if (currentDiff !== 0) {
        return currentDiff;
      }
      return scoreItem(b) - scoreItem(a);
    })
    .slice(0, 8);

  for (const item of targets) {
    autoProbeUrls.add(item.url);
    await chrome.runtime.sendMessage({
      target: "background",
      action: "PROBE_MEDIA",
      url: item.url,
      tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
      pageUrl: forcedPageUrl || undefined
    }).catch(() => {});
  }
}

function renderRecentDownloads(items) {
  recentDownloadsContainer.innerHTML = "";
  if (!items.length) {
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "recent-card";
  wrapper.innerHTML = `
    <div class="section-header">
      <h2 class="section-title">最近完成</h2>
      <span class="small">保留最近 ${items.length} 条</span>
    </div>
    <div class="recent-list"></div>
  `;

  const list = wrapper.querySelector(".recent-list");
  for (const item of items.slice(0, 5)) {
    const row = document.createElement("div");
    row.className = "recent-card";
    row.innerHTML = `
      <div class="card-header">
        <strong>${escapeHtml(item.filename || "已完成下载")}</strong>
        <span class="tag">完成</span>
      </div>
        <div class="recent-meta">${escapeHtml(getAuthorDateLabel(item) || compactPath(item.outputPath || "") || shortUrl(item.pageUrl || ""))}</div>
      ${item.outputPath
        ? `<div class="recent-actions">
            <button class="button secondary" data-action="open-output" data-path="${escapeHtml(item.outputPath)}">打开位置</button>
          </div>`
        : ""}
    `;
    list.appendChild(row);
  }

  recentDownloadsContainer.appendChild(wrapper);
}

function renderJobs(jobs) {
  jobsContainer.innerHTML = "";
  if (!jobs.length) {
    return;
  }

  for (const job of jobs) {
    const card = document.createElement("div");
    card.className = "job";
    const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
    card.innerHTML = `
      <div class="card-header">
        <strong>${job.filename}</strong>
        <span class="tag">${job.status}</span>
      </div>
      <div class="small">${escapeHtml(getAuthorDateLabel(job))}</div>
      <div class="source-line">${escapeHtml(getItemSubline(job) || shortUrl(job.url))}</div>
      <div class="progress"><span style="width:${progress}%"></span></div>
      <div class="small ${job.status === "error" ? "error" : ""}">${job.message || ""}</div>
      ${job.status === "done" && job.outputPath
        ? `<div class="recent-actions"><button class="button secondary" data-action="open-output" data-path="${escapeHtml(job.outputPath)}">打开位置</button></div>`
        : ""}
    `;
    jobsContainer.appendChild(card);
  }
}

function renderFeatured(item) {
  featuredContainer.innerHTML = "";
}

function renderItems(items, primaryOnlyEnabled, recommendedItem) {
  itemsContainer.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = primaryOnlyEnabled
      ? "当前还没筛出像主视频的候选，先播放视频、点“探测”，或先关闭“只看主视频”。"
      : "当前页还没有抓到可用媒体，先播放视频或点“刷新探测”。";
    itemsContainer.appendChild(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("div");
    const isRecommended = recommendedItem && recommendedItem.url === item.url;
    card.className = isRecommended ? "card recommended" : "card";

    const thumbnailSrc = getThumbnailSrc(item);
    const authorDateLabel = getAuthorDateLabel(item);
    const sourceMeta = getUrlMeta(item.url);
    const dimensions = item.width && item.height ? `${item.width}x${item.height}` : "";
    const details = [
      authorDateLabel,
      item.duration ? formatDuration(item.duration) : "",
      dimensions,
      item.contentLength ? formatBytes(item.contentLength) : "",
      item.source || ""
    ].filter(Boolean);
    const tags = [];

    if (isRecommended) {
      tags.push("推荐");
    }
    if (currentActiveVideoHint && isCurrentVideoCandidate(item, currentActiveVideoHint)) {
      tags.push("当前视频");
    }
    if (scoreItem(item) >= 300) {
      tags.push("优先");
    }
    if (item.requestHeaders && Object.keys(item.requestHeaders).length > 0) {
      tags.push("带请求头");
    }
    if (analyzeUrl(item.url).isDecorativeAsset) {
      tags.push("疑似素材");
    }
    if (isLikelyFragment(item)) {
      tags.push("疑似碎片");
    }
    if (item.kind && tags.length < 4) {
      tags.push(item.kind);
    }

    card.innerHTML = `
      <div class="card-media">
        ${thumbnailSrc
          ? `<img class="card-thumb" src="${escapeHtml(thumbnailSrc)}" alt="视频缩略图">`
          : `<div class="card-thumb placeholder">暂无缩略图</div>`}
      </div>
      <div class="card-body">
        <div class="card-main">
          <div class="card-text">
            <h2 class="card-title">${escapeHtml(getItemHeadline(item))}</h2>
            <div class="card-meta">${escapeHtml(details.join(" · ") || getItemSubline(item) || "视频资源")}</div>
          </div>
        </div>
        ${sourceMeta.path ? `<div class="source-line">${escapeHtml(sourceMeta.path)}</div>` : ""}
        <div class="tag-row">
          ${tags.slice(0, 5).map((tag) => `<span class="tag ${tag === "推荐" ? "recommend-chip" : ""}">${escapeHtml(tag)}</span>`).join("")}
        </div>
        <div class="card-actions">
          ${canCompleteDownload(item)
            ? `<button class="button primary" data-action="download-complete" data-url="${escapeHtml(item.url)}">下载</button>`
            : ""}
          <button class="button ghost" data-action="probe" data-url="${escapeHtml(item.url)}">探测</button>
          <button class="button ghost" data-action="copy" data-url="${escapeHtml(item.url)}">复制</button>
        </div>
      </div>
    `;
    itemsContainer.appendChild(card);
  }
}

document.getElementById("refresh-btn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({
    target: "background",
    action: "RESCAN_ACTIVE_TAB",
    tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
    pageUrl: forcedPageUrl || undefined
  });
  await refreshState();
});

document.getElementById("clear-btn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({
    target: "background",
    action: "CLEAR_ACTIVE_TAB_STATE",
    tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
    pageUrl: forcedPageUrl || undefined
  });
  await refreshState();
});

primaryOnlyToggle.checked = getPrimaryOnlyEnabled();
primaryOnlyToggle.addEventListener("change", () => {
  setPrimaryOnlyEnabled(primaryOnlyToggle.checked);
  void refreshState();
});

document.body.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  const action = target.dataset.action;
  if (!action) {
    return;
  }

  if (action === "copy") {
    const url = target.dataset.url;
    if (!url) {
      return;
    }
    await navigator.clipboard.writeText(url);
    target.textContent = "已复制";
    setTimeout(() => {
      target.textContent = "复制";
    }, 1200);
    return;
  }

  if (action === "open-output") {
    target.disabled = true;
    await chrome.runtime.sendMessage({
      target: "background",
      action: "OPEN_OUTPUT_PATH",
      path: target.dataset.path || ""
    }).catch(() => {});
    target.disabled = false;
    return;
  }

  const url = target.dataset.url;
  if (!url) {
    return;
  }

  if (action === "download-complete") {
    target.disabled = true;
    target.textContent = "抓取中...";
    await chrome.runtime.sendMessage({
      target: "background",
      action: "DOWNLOAD_COMPLETE_MEDIA",
      url,
      tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
      pageUrl: forcedPageUrl || undefined
    }).catch(() => {});
    setTimeout(refreshState, 500);
    setTimeout(refreshState, 1500);
    setTimeout(refreshState, 3000);
    target.disabled = false;
    target.textContent = "下载";
    return;
  }

  if (action === "probe") {
    target.disabled = true;
    target.textContent = "探测中...";
    await chrome.runtime.sendMessage({
      target: "background",
      action: "PROBE_MEDIA",
      url,
      tabId: Number.isFinite(forcedTabId) ? forcedTabId : undefined,
      pageUrl: forcedPageUrl || undefined
    });
    await refreshState();
    target.disabled = false;
    target.textContent = "探测";
  }
});

refreshState();
setInterval(refreshState, 1500);
