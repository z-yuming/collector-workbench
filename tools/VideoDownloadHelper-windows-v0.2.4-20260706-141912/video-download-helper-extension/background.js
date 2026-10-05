const tabMedia = new Map();
const tabUrls = new Map();
const pendingRequestHeaders = new Map();
const downloadJobs = new Map();
const reportTimers = new Map();

let offscreenReadyPromise = null;
const REPORT_ENDPOINT = "http://127.0.0.1:8766/report";
const COMPLETE_DOWNLOAD_ENDPOINT = "http://127.0.0.1:8766/complete-download";
const OPEN_PATH_ENDPOINT = "http://127.0.0.1:8766/open-path";
const RECENT_DOWNLOADS_KEY = "videoGrab.recentDownloads";
const MAX_RECENT_DOWNLOADS = 8;

function buildMediaFilenameBase(media) {
  const authorName = String(media.authorName || "").trim();
  const publishDate = String(media.publishDate || "").trim();
  if (authorName && publishDate) {
    return `${authorName}_${publishDate}`;
  }
  if (authorName) {
    return authorName;
  }
  if (publishDate) {
    return publishDate;
  }
  return media.pageTitle || media.title || "download";
}

function sanitizeRecentDownload(entry) {
  return {
    filename: String(entry.filename || ""),
    outputPath: String(entry.outputPath || ""),
    pageUrl: String(entry.pageUrl || ""),
    authorName: String(entry.authorName || ""),
    publishDate: String(entry.publishDate || ""),
    createdAt: Number(entry.createdAt || Date.now())
  };
}

async function getRecentDownloads() {
  const stored = await chrome.storage.local.get(RECENT_DOWNLOADS_KEY).catch(() => ({}));
  const items = Array.isArray(stored[RECENT_DOWNLOADS_KEY]) ? stored[RECENT_DOWNLOADS_KEY] : [];
  return items.map(sanitizeRecentDownload);
}

async function saveRecentDownloads(items) {
  await chrome.storage.local.set({
    [RECENT_DOWNLOADS_KEY]: items.slice(0, MAX_RECENT_DOWNLOADS).map(sanitizeRecentDownload)
  }).catch(() => {});
}

async function addRecentDownload(entry) {
  const nextEntry = sanitizeRecentDownload(entry);
  const existing = await getRecentDownloads();
  const deduped = existing.filter((item) => item.outputPath !== nextEntry.outputPath);
  deduped.unshift(nextEntry);
  await saveRecentDownloads(deduped);
}

function getTabBucket(tabId) {
  if (!tabMedia.has(tabId)) {
    tabMedia.set(tabId, {
      items: [],
      seenKeys: new Set(),
      lastUpdated: Date.now(),
      pageContext: {
        activeVideo: null
      }
    });
  }
  return tabMedia.get(tabId);
}

function sanitizeHeaders(headers) {
  const allowed = new Set([
    "authorization",
    "cookie",
    "origin",
    "referer",
    "user-agent"
  ]);
  const result = {};
  for (const header of headers || []) {
    const name = String(header.name || "").toLowerCase();
    if (!allowed.has(name) || !header.value) {
      continue;
    }
    result[name] = header.value;
  }
  return result;
}

function parseResponseHeaders(headers) {
  const result = {
    contentLength: null,
    contentType: "",
    rangeFrom: 0,
    totalLength: null
  };

  for (const header of headers || []) {
    const name = String(header.name || "").toLowerCase();
    const value = String(header.value || "");
    if (name === "content-type") {
      result.contentType = value.split(";")[0].trim().toLowerCase();
    } else if (name === "content-length") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed)) {
        result.contentLength = parsed;
      }
    } else if (name === "content-range") {
      const match = value.match(/bytes\s+(\d+)-(\d+)\/(\d+|\*)/i);
      if (match) {
        result.rangeFrom = Number.parseInt(match[1], 10) || 0;
        const totalLength = Number.parseInt(match[3], 10);
        if (Number.isFinite(totalLength) && totalLength > 0) {
          result.totalLength = totalLength;
        }
      }
    }
  }

  if (Number.isFinite(result.totalLength) && result.totalLength > 0) {
    result.contentLength = result.totalLength;
  }

  return result;
}

function looksLikeMediaUrl(url) {
  if (!url) {
    return false;
  }

  const lowered = url.toLowerCase();
  return (
    lowered.includes(".mp4") ||
    lowered.includes(".m3u8") ||
    lowered.includes(".webm") ||
    lowered.includes(".mov") ||
    lowered.includes(".m4v") ||
    lowered.includes(".mp3") ||
    lowered.includes(".m4a") ||
    lowered.includes(".ts") ||
    lowered.includes("playaddr") ||
    lowered.includes("playapi")
  );
}

function looksLikeMediaResponse(url, contentType, requestType) {
  if (looksLikeMediaUrl(url)) {
    return true;
  }

  if (
    contentType === "video/mp4" ||
    contentType === "video/webm" ||
    contentType === "video/quicktime" ||
    contentType === "video/mp2t" ||
    contentType === "audio/mp4" ||
    contentType === "audio/mpeg" ||
    contentType === "application/vnd.apple.mpegurl" ||
    contentType === "application/x-mpegurl"
  ) {
    return true;
  }

  return contentType === "application/octet-stream" && requestType === "media";
}

function guessKind(url, contentType) {
  const loweredUrl = String(url || "").toLowerCase();
  const loweredType = String(contentType || "").toLowerCase();

  if (loweredUrl.includes(".m3u8") || loweredType.includes("mpegurl")) {
    return "m3u8";
  }
  if (
    loweredUrl.includes("media-audio") ||
    loweredUrl.includes(".mp3") ||
    loweredUrl.includes(".m4a") ||
    loweredType.startsWith("audio/")
  ) {
    return "audio";
  }
  if (loweredUrl.includes(".ts") || loweredType === "video/mp2t") {
    return "segment";
  }
  return "video";
}

function mergeMediaItem(tabId, item) {
  if (typeof tabId !== "number" || tabId < 0 || !item || !item.url) {
    return false;
  }

  const bucket = getTabBucket(tabId);
  const normalizedUrl = item.url.trim();
  const dedupeKey = [
    normalizedUrl,
    item.kind || "",
    item.contentType || "",
    item.contentLength || ""
  ].join("|");

  const existingIndex = bucket.items.findIndex((entry) => entry.url === normalizedUrl);
  if (existingIndex >= 0) {
    bucket.items[existingIndex] = {
      ...bucket.items[existingIndex],
      ...item,
      url: normalizedUrl
    };
    bucket.lastUpdated = Date.now();
    updateBadge(tabId);
    scheduleReport(tabId);
    return true;
  }

  if (bucket.seenKeys.has(dedupeKey)) {
    return false;
  }

  bucket.seenKeys.add(dedupeKey);
  bucket.items.unshift({
    ...item,
    url: normalizedUrl,
    discoveredAt: Date.now()
  });
  bucket.items = bucket.items.slice(0, 200);
  bucket.lastUpdated = Date.now();
  updateBadge(tabId);
  scheduleReport(tabId);
  return true;
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true
  });
  return tab || null;
}

async function resolveTabByMessage(message) {
  if (typeof message.tabId === "number" && message.tabId >= 0) {
    try {
      return await chrome.tabs.get(message.tabId);
    } catch (_error) {
      return null;
    }
  }
  if (typeof message.pageUrl === "string" && message.pageUrl) {
    const matched = await chrome.tabs.query({});
    const tab = matched.find((entry) => entry.url === message.pageUrl);
    if (tab) {
      return tab;
    }
  }
  return await getActiveTab();
}

function serializeBucket(tabId) {
  const bucket = getTabBucket(tabId);
  return {
    items: bucket.items,
    lastUpdated: bucket.lastUpdated,
    tabUrl: tabUrls.get(tabId) || "",
    pageContext: bucket.pageContext || { activeVideo: null },
    jobs: Array.from(downloadJobs.values()).filter((job) => job.tabId === tabId)
  };
}

async function reportTabState(tabId) {
  if (typeof tabId !== "number" || tabId < 0) {
    return;
  }

  try {
    await fetch(REPORT_ENDPOINT, {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        tabId,
        reportedAt: Date.now(),
        state: serializeBucket(tabId)
      }),
      keepalive: true
    });
  } catch (_error) {
    // Best-effort local reporting only.
  }
}

function scheduleReport(tabId) {
  if (typeof tabId !== "number" || tabId < 0) {
    return;
  }

  if (reportTimers.has(tabId)) {
    clearTimeout(reportTimers.get(tabId));
  }

  const timer = setTimeout(() => {
    reportTimers.delete(tabId);
    void reportTabState(tabId);
  }, 250);

  reportTimers.set(tabId, timer);
}

function updateBadge(tabId) {
  const bucket = getTabBucket(tabId);
  const count = bucket.items.length;
  chrome.action.setBadgeBackgroundColor({ color: "#2563eb" }).catch(() => {});
  chrome.action.setBadgeText({
    tabId,
    text: count > 0 ? String(Math.min(count, 99)) : ""
  }).catch(() => {});
}

async function ensureOffscreen() {
  if (offscreenReadyPromise) {
    return offscreenReadyPromise;
  }

  offscreenReadyPromise = (async () => {
    try {
      if (chrome.runtime.getContexts) {
        const contexts = await chrome.runtime.getContexts({
          contextTypes: ["OFFSCREEN_DOCUMENT"],
          documentUrls: [chrome.runtime.getURL("offscreen.html")]
        });
        if (contexts.length > 0) {
          return;
        }
      }

      await chrome.offscreen.createDocument({
        url: "offscreen.html",
        reasons: ["BLOBS"],
        justification: "Need a DOM context to fetch media with custom headers and save blobs."
      });
    } catch (error) {
      const text = String(error && error.message ? error.message : error);
      if (!text.includes("single offscreen document")) {
        throw error;
      }
    } finally {
      offscreenReadyPromise = null;
    }
  })();

  return offscreenReadyPromise;
}

function createDownloadJob(tabId, media) {
  const id = crypto.randomUUID();
  const job = {
    id,
    tabId,
    url: media.url,
    filename: media.filename || buildMediaFilenameBase(media),
    authorName: media.authorName || "",
    publishDate: media.publishDate || "",
    status: "queued",
    progress: 0,
    message: "",
    kind: media.kind || "video",
    outputPath: media.outputPath || "",
    createdAt: Date.now()
  };
  downloadJobs.set(id, job);
  return job;
}

async function requestCompleteDownload(tabId, media) {
  const response = await fetch(COMPLETE_DOWNLOAD_ENDPOINT, {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({
      tabId,
      authorName: media.authorName || "",
      videoTitle: media.videoTitle || "",
      publishDate: media.publishDate || "",
      pageTitle: media.pageTitle || media.title || "",
      pageUrl: media.pageUrl || "",
      selected: media,
      items: getTabBucket(tabId).items
    })
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `Complete download failed: ${response.status}`);
  }
  return payload;
}

async function openOutputPath(path) {
  const response = await fetch(OPEN_PATH_ENDPOINT, {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ path })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `Open path failed: ${response.status}`);
  }
  return payload;
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "loading" && tab.url && tabUrls.get(tabId) !== tab.url) {
    tabUrls.set(tabId, tab.url);
    tabMedia.set(tabId, {
      items: [],
      seenKeys: new Set(),
      lastUpdated: Date.now(),
      pageContext: {
        activeVideo: null
      }
    });
    updateBadge(tabId);
    scheduleReport(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  tabMedia.delete(tabId);
  tabUrls.delete(tabId);
  if (reportTimers.has(tabId)) {
    clearTimeout(reportTimers.get(tabId));
    reportTimers.delete(tabId);
  }
  for (const [jobId, job] of downloadJobs) {
    if (job.tabId === tabId) {
      downloadJobs.delete(jobId);
    }
  }
});

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (details.initiator && details.initiator.startsWith("chrome-extension://")) {
      return;
    }
    pendingRequestHeaders.set(details.requestId, sanitizeHeaders(details.requestHeaders));
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onHeadersReceived.addListener(
  async (details) => {
    if (details.statusCode >= 400 || details.method === "OPTIONS") {
      pendingRequestHeaders.delete(details.requestId);
      return;
    }

    const requestHeaders = pendingRequestHeaders.get(details.requestId) || {};
    pendingRequestHeaders.delete(details.requestId);

    const response = parseResponseHeaders(details.responseHeaders);
    if (!looksLikeMediaResponse(details.url, response.contentType, details.type)) {
      return;
    }

    if (response.rangeFrom > 0 && response.rangeFrom < 100) {
      return;
    }

    let pageTitle = "";
    let pageUrl = tabUrls.get(details.tabId) || "";
    try {
      const tab = await chrome.tabs.get(details.tabId);
      pageTitle = tab.title || "";
      pageUrl = tab.url || pageUrl;
      tabUrls.set(details.tabId, pageUrl);
    } catch (_error) {
      // Ignore tabs that disappeared between the request and the lookup.
    }

    mergeMediaItem(details.tabId, {
      url: details.url,
      kind: guessKind(details.url, response.contentType),
      source: "network",
      contentType: response.contentType,
      contentLength: response.contentLength,
      requestHeaders,
      pageTitle,
      pageUrl
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

chrome.webRequest.onErrorOccurred.addListener(
  (details) => {
    pendingRequestHeaders.delete(details.requestId);
  },
  { urls: ["<all_urls>"] }
);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message.target && message.target !== "background") {
      return;
    }

    if (message.action === "PAGE_CANDIDATES") {
      const tabId = sender.tab && typeof sender.tab.id === "number" ? sender.tab.id : -1;
      if (tabId >= 0) {
        for (const candidate of message.candidates || []) {
          mergeMediaItem(tabId, {
            ...candidate,
            source: candidate.source || "dom",
            pageTitle: sender.tab.title || candidate.pageTitle || "",
            pageUrl: sender.tab.url || candidate.pageUrl || ""
          });
        }
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "GET_ACTIVE_TAB_STATE") {
      const tab = await resolveTabByMessage(message);
      const recentDownloads = await getRecentDownloads();
      sendResponse({
        ok: true,
        tabId: tab ? tab.id : -1,
        title: tab ? tab.title || "" : "",
        url: tab ? tab.url || "" : "",
        state: tab ? serializeBucket(tab.id) : { items: [], jobs: [], lastUpdated: Date.now(), tabUrl: "" },
        recentDownloads
      });
      return;
    }

    if (message.action === "CLEAR_ACTIVE_TAB_STATE") {
      const tab = await resolveTabByMessage(message);
      if (tab) {
        tabMedia.set(tab.id, {
          items: [],
          seenKeys: new Set(),
          lastUpdated: Date.now(),
          pageContext: {
            activeVideo: null
          }
        });
        updateBadge(tab.id);
        scheduleReport(tab.id);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "PAGE_CONTEXT") {
      const tabId = sender.tab && typeof sender.tab.id === "number" ? sender.tab.id : -1;
      if (tabId >= 0) {
        const bucket = getTabBucket(tabId);
        bucket.pageContext = message.pageContext || { activeVideo: null };
        bucket.lastUpdated = Date.now();
        scheduleReport(tabId);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "RESCAN_ACTIVE_TAB") {
      const tab = await resolveTabByMessage(message);
      if (tab && typeof tab.id === "number") {
        await chrome.tabs.sendMessage(tab.id, { action: "RESCAN_DOM" }).catch(() => {});
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "DOWNLOAD_MEDIA") {
      const tab = await resolveTabByMessage(message);
      if (!tab) {
        sendResponse({ ok: false, error: "No active tab" });
        return;
      }

      const item = getTabBucket(tab.id).items.find((entry) => entry.url === message.url);
      if (!item) {
        sendResponse({ ok: false, error: "Media item not found" });
        return;
      }

      const job = createDownloadJob(tab.id, item);
      await ensureOffscreen();
      await chrome.runtime.sendMessage({
        target: "offscreen",
        action: "OFFSCREEN_DOWNLOAD",
        jobId: job.id,
        media: item
      });
      sendResponse({ ok: true, jobId: job.id });
      return;
    }

    if (message.action === "DOWNLOAD_COMPLETE_MEDIA") {
      const tab = await resolveTabByMessage(message);
      if (!tab) {
        sendResponse({ ok: false, error: "No active tab" });
        return;
      }

      const item = getTabBucket(tab.id).items.find((entry) => entry.url === message.url);
      if (!item) {
        sendResponse({ ok: false, error: "Media item not found" });
        return;
      }

      const job = createDownloadJob(tab.id, {
        ...item,
        filename: buildMediaFilenameBase(item)
      });
      job.status = "processing";
      job.message = "正在补音频并合成完整视频";
      job.progress = 10;
      scheduleReport(tab.id);

      try {
        const result = await requestCompleteDownload(tab.id, item);
        job.status = "done";
        job.progress = 100;
        job.message = `完整视频已保存到 ${result.outputPath}`;
        job.outputPath = result.outputPath || "";
        if (result.outputName) {
          job.filename = result.outputName;
        }
        await addRecentDownload({
          filename: result.outputName || job.filename,
          outputPath: result.outputPath || "",
          pageUrl: item.pageUrl || tab.url || "",
          authorName: item.authorName || "",
          publishDate: item.publishDate || "",
          createdAt: Date.now()
        });
        scheduleReport(tab.id);
        sendResponse({ ok: true, jobId: job.id, result });
      } catch (error) {
        job.status = "error";
        job.message = String(error && error.message ? error.message : error);
        scheduleReport(tab.id);
        sendResponse({ ok: false, error: job.message, jobId: job.id });
      }
      return;
    }

    if (message.action === "OPEN_OUTPUT_PATH") {
      await openOutputPath(message.path || "");
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "PROBE_MEDIA") {
      const tab = await resolveTabByMessage(message);
      if (!tab) {
        sendResponse({ ok: false, error: "No active tab" });
        return;
      }

      const item = getTabBucket(tab.id).items.find((entry) => entry.url === message.url);
      if (!item) {
        sendResponse({ ok: false, error: "Media item not found" });
        return;
      }

      await ensureOffscreen();
      const response = await chrome.runtime.sendMessage({
        target: "offscreen",
        action: "OFFSCREEN_PROBE",
        media: item
      });
      if (response && response.ok && response.metadata) {
        mergeMediaItem(tab.id, {
          ...item,
          ...response.metadata
        });
      }
      sendResponse(response);
      return;
    }

    if (message.action === "OFFSCREEN_DOWNLOAD_PROGRESS") {
      const job = downloadJobs.get(message.jobId);
      if (job) {
        job.status = message.status || job.status;
        job.progress = message.progress ?? job.progress;
        job.message = message.message || "";
        scheduleReport(job.tabId);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.action === "OFFSCREEN_DOWNLOAD_DONE") {
      const job = downloadJobs.get(message.jobId);
      if (job) {
        job.status = message.ok ? "done" : "error";
        job.progress = message.ok ? 100 : job.progress;
        job.message = message.message || "";
        scheduleReport(job.tabId);
      }
      sendResponse({ ok: true });
      return;
    }

    sendResponse({ ok: false, error: "Unknown action" });
  })().catch((error) => {
    sendResponse({
      ok: false,
      error: String(error && error.message ? error.message : error)
    });
  });

  return true;
});
