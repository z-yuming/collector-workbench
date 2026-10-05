(function () {
  const HOOK_SOURCE = "__media_catcher_hook__";
  const seenDomUrls = new Set();
  const THUMBNAIL_KEYWORDS = [
    "poster",
    "cover",
    "thumb",
    "image",
    "img",
    "snapshot"
  ];
  let extensionContextAlive = true;
  let domObserver = null;

  function isContextInvalidatedError(error) {
    const message = String(error && error.message ? error.message : error || "");
    return (
      message.includes("Extension context invalidated") ||
      message.includes("Receiving end does not exist") ||
      message.includes("context invalidated")
    );
  }

  function teardown() {
    if (!extensionContextAlive) {
      return;
    }
    extensionContextAlive = false;
    if (domObserver) {
      domObserver.disconnect();
      domObserver = null;
    }
    window.removeEventListener("message", handleWindowMessage);
    document.removeEventListener("play", handlePlaybackEvent, true);
    document.removeEventListener("pause", handlePlaybackEvent, true);
    document.removeEventListener("timeupdate", handlePlaybackEvent, true);
  }

  async function safeSendMessage(message) {
    if (!extensionContextAlive || !chrome.runtime?.id) {
      teardown();
      return null;
    }

    try {
      return await chrome.runtime.sendMessage(message);
    } catch (error) {
      if (isContextInvalidatedError(error)) {
        teardown();
        return null;
      }
      throw error;
    }
  }

  function injectHook() {
    if (document.documentElement.dataset.mediaCatcherHookInjected === "true") {
      return;
    }

    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("page-hook.js");
    script.async = false;
    script.dataset.source = HOOK_SOURCE;
    script.onload = () => {
      script.remove();
    };
    (document.head || document.documentElement).appendChild(script);
    document.documentElement.dataset.mediaCatcherHookInjected = "true";
  }

  function looksLikeMediaUrl(value) {
    if (typeof value !== "string") {
      return false;
    }
    const url = value.trim().toLowerCase();
    return (
      url.startsWith("http://") ||
      url.startsWith("https://")
    ) && (
      url.includes(".mp4") ||
      url.includes(".m3u8") ||
      url.includes(".webm") ||
      url.includes(".mov") ||
      url.includes(".m4v") ||
      url.includes(".mp3") ||
      url.includes(".m4a") ||
      url.includes(".ts") ||
      url.includes("playaddr") ||
      url.includes("playapi")
    );
  }

  function guessKind(url) {
    const lowered = String(url || "").toLowerCase();
    if (lowered.includes(".m3u8")) {
      return "m3u8";
    }
    if (lowered.includes("media-audio") || lowered.includes(".mp3") || lowered.includes(".m4a")) {
      return "audio";
    }
    if (lowered.includes(".ts")) {
      return "segment";
    }
    return "video";
  }

  function normalizeUrl(url) {
    try {
      return new URL(url, location.href).toString();
    } catch (_error) {
      return "";
    }
  }

  function extractUrlLikeString(value, visited = new WeakSet(), depth = 0) {
    if (depth > 4 || value == null) {
      return "";
    }

    if (typeof value === "string") {
      return normalizeUrl(value);
    }

    if (typeof value !== "object") {
      return "";
    }

    if (visited.has(value)) {
      return "";
    }
    visited.add(value);

    if (Array.isArray(value)) {
      for (const entry of value.slice(0, 10)) {
        const url = extractUrlLikeString(entry, visited, depth + 1);
        if (url) {
          return url;
        }
      }
      return "";
    }

    const directKeys = ["url", "src", "uri", "download_url"];
    for (const key of directKeys) {
      if (typeof value[key] === "string") {
        const url = normalizeUrl(value[key]);
        if (url) {
          return url;
        }
      }
    }

    if (Array.isArray(value.url_list)) {
      for (const entry of value.url_list.slice(0, 10)) {
        if (typeof entry === "string") {
          const url = normalizeUrl(entry);
          if (url) {
            return url;
          }
        }
      }
    }

    for (const nestedValue of Object.values(value).slice(0, 20)) {
      const url = extractUrlLikeString(nestedValue, visited, depth + 1);
      if (url) {
        return url;
      }
    }

    return "";
  }

  function extractThumbnailUrl(value, visited = new WeakSet(), depth = 0) {
    if (depth > 4 || value == null || typeof value !== "object") {
      return "";
    }

    if (visited.has(value)) {
      return "";
    }
    visited.add(value);

    if (Array.isArray(value)) {
      for (const entry of value.slice(0, 50)) {
        const thumbnailUrl = extractThumbnailUrl(entry, visited, depth + 1);
        if (thumbnailUrl) {
          return thumbnailUrl;
        }
      }
      return "";
    }

    for (const [key, nestedValue] of Object.entries(value)) {
      const loweredKey = key.toLowerCase();
      if (THUMBNAIL_KEYWORDS.some((keyword) => loweredKey.includes(keyword))) {
        const thumbnailUrl = extractUrlLikeString(nestedValue);
        if (thumbnailUrl) {
          return thumbnailUrl;
        }
      }
    }

    for (const nestedValue of Object.values(value).slice(0, 50)) {
      const thumbnailUrl = extractThumbnailUrl(nestedValue, visited, depth + 1);
      if (thumbnailUrl) {
        return thumbnailUrl;
      }
    }

    return "";
  }

  function normalizeLabel(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function extractAuthorName(value) {
    if (!value || typeof value !== "object") {
      return "";
    }

    const author = value.author;
    if (author && typeof author === "object") {
      const directAuthor = normalizeLabel(
        author.nickname ||
        author.author_name ||
        author.authorName ||
        author.display_name ||
        author.unique_id
      );
      if (directAuthor) {
        return directAuthor;
      }
    }

    return normalizeLabel(
      value.nickname ||
      value.author_name ||
      value.authorName ||
      value.display_name
    );
  }

  function extractVideoTitle(value) {
    if (!value || typeof value !== "object") {
      return "";
    }

    const direct = normalizeLabel(
      value.desc ||
      value.description ||
      value.title ||
      value.content ||
      value.caption ||
      value.name
    );
    if (direct && !/^https?:\/\//i.test(direct)) {
      return direct;
    }

    return "";
  }

  function formatPublishDate(value) {
    if (value == null || value === "") {
      return "";
    }

    if (typeof value === "number" && Number.isFinite(value)) {
      const timestamp = value > 1_000_000_000_000 ? value : value * 1000;
      const date = new Date(timestamp);
      if (!Number.isNaN(date.getTime())) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
      }
    }

    const text = normalizeLabel(value);
    if (!text) {
      return "";
    }

    let match = text.match(/(\d{4})[\/\-年](\d{1,2})[\/\-月](\d{1,2})/);
    if (match) {
      const [, year, month, day] = match;
      return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }

    match = text.match(/^(\d{1,2})月(\d{1,2})日$/);
    if (match) {
      const [, month, day] = match;
      return `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }

    return "";
  }

  function extractPublishDate(value) {
    if (!value || typeof value !== "object") {
      return "";
    }

    const direct = formatPublishDate(
      value.create_time ??
      value.publish_time ??
      value.aweme_create_time ??
      value.createTime ??
      value.publishTime ??
      value.date
    );
    if (direct) {
      return direct;
    }

    if (value.statistics && typeof value.statistics === "object") {
      const nested = formatPublishDate(value.statistics.create_time ?? value.statistics.publish_time);
      if (nested) {
        return nested;
      }
    }

    return "";
  }

  function pushCandidate(candidates, candidate) {
    if (!candidate || !candidate.url) {
      return;
    }
    const url = normalizeUrl(candidate.url);
    if (!url || !looksLikeMediaUrl(url)) {
      return;
    }
    candidates.push({
      url,
      kind: candidate.kind || guessKind(url),
      source: candidate.source || "hook",
      title: document.title,
      pageUrl: location.href,
      contentType: candidate.contentType || "",
      duration: candidate.duration || null,
      width: candidate.width || null,
      height: candidate.height || null,
      authorName: candidate.authorName || "",
      videoTitle: candidate.videoTitle || "",
      publishDate: candidate.publishDate || "",
      ...(candidate.thumbnailUrl ? { thumbnailUrl: normalizeUrl(candidate.thumbnailUrl) || candidate.thumbnailUrl } : {})
    });
  }

  function getIntersectionRatio(rect) {
    const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
    const visibleArea = width * height;
    const totalArea = Math.max(1, rect.width * rect.height);
    return visibleArea / totalArea;
  }

  function getVideoPriority(video) {
    const rect = video.getBoundingClientRect();
    const intersectionRatio = getIntersectionRatio(rect);
    const visibleArea = Math.max(0, rect.width) * Math.max(0, rect.height) * intersectionRatio;
    let score = visibleArea;

    if (!video.paused) {
      score += 1_000_000;
    }
    if (video.currentTime > 0.2) {
      score += 200_000;
    }
    if (intersectionRatio > 0.6) {
      score += 120_000;
    }
    if (video.videoHeight > video.videoWidth) {
      score += 20_000;
    }

    return score;
  }

  function getPageContext() {
    const videos = Array.from(document.querySelectorAll("video"));
    if (!videos.length) {
      return {
        activeVideo: null
      };
    }

    const ranked = videos
      .map((video) => {
        const rect = video.getBoundingClientRect();
        return {
          video,
          score: getVideoPriority(video),
          intersectionRatio: getIntersectionRatio(rect)
        };
      })
      .sort((left, right) => right.score - left.score);

    const current = ranked[0];
    if (!current) {
      return {
        activeVideo: null
      };
    }

    return {
      activeVideo: {
        duration: Number.isFinite(current.video.duration) ? current.video.duration : null,
        width: current.video.videoWidth || null,
        height: current.video.videoHeight || null,
        currentTime: Number.isFinite(current.video.currentTime) ? current.video.currentTime : 0,
        paused: Boolean(current.video.paused),
        intersectionRatio: current.intersectionRatio,
        blobUrl: normalizeUrl(current.video.currentSrc || current.video.src || "")
      }
    };
  }

  function scanDomForCandidates() {
    const candidates = [];
    const videos = document.querySelectorAll("video");
    for (const video of videos) {
      const urls = [video.currentSrc, video.src];
      const source = video.querySelector("source");
      if (source && source.src) {
        urls.push(source.src);
      }
      for (const url of urls) {
        if (!url) {
          continue;
        }
        const normalized = normalizeUrl(url);
        if (!normalized || seenDomUrls.has(normalized)) {
          continue;
        }
        seenDomUrls.add(normalized);
        pushCandidate(candidates, {
          url: normalized,
          source: "dom",
          duration: Number.isFinite(video.duration) ? video.duration : null,
          width: video.videoWidth || null,
          height: video.videoHeight || null,
          thumbnailUrl: video.poster || ""
        });
      }
    }
    return candidates;
  }

  function extractCandidatesFromObject(root) {
    const candidates = [];
    const visited = new WeakSet();

    function visit(value, depth) {
      if (depth > 7 || value == null) {
        return;
      }

      if (typeof value === "string") {
        if (looksLikeMediaUrl(value)) {
          pushCandidate(candidates, { url: value, source: "api" });
        }
        return;
      }

      if (typeof value !== "object") {
        return;
      }

      if (visited.has(value)) {
        return;
      }
      visited.add(value);

      if (Array.isArray(value)) {
        for (const entry of value.slice(0, 100)) {
          visit(entry, depth + 1);
        }
        return;
      }

      const sharedThumbnailUrl = extractThumbnailUrl(value);
      const sharedAuthorName = extractAuthorName(value);
      const sharedVideoTitle = extractVideoTitle(value);
      const sharedPublishDate = extractPublishDate(value);
      const directKeys = [
        "url",
        "playAddr",
        "playApi",
        "play_url",
        "masterUrl",
        "stream_url",
        "photoUrl",
        "src"
      ];

      for (const key of directKeys) {
        const directValue = value[key];
        if (typeof directValue === "string") {
          pushCandidate(candidates, {
            url: directValue,
            source: "api",
            duration: Number(value.duration) || null,
            width: Number(value.width) || null,
            height: Number(value.height) || null,
            authorName: sharedAuthorName,
            videoTitle: sharedVideoTitle,
            publishDate: sharedPublishDate,
            thumbnailUrl: sharedThumbnailUrl
          });
        } else if (Array.isArray(directValue)) {
          for (const entry of directValue.slice(0, 10)) {
            if (typeof entry === "string") {
              pushCandidate(candidates, {
                url: entry,
                source: "api",
                duration: Number(value.duration) || null,
                width: Number(value.width) || null,
                height: Number(value.height) || null,
                authorName: sharedAuthorName,
                videoTitle: sharedVideoTitle,
                publishDate: sharedPublishDate,
                thumbnailUrl: sharedThumbnailUrl
              });
            }
          }
        }
      }

      if (Array.isArray(value.url_list)) {
        for (const url of value.url_list.slice(0, 10)) {
          if (typeof url === "string") {
            pushCandidate(candidates, {
              url,
              source: "api",
              duration: Number(value.duration) || null,
              width: Number(value.width) || null,
              height: Number(value.height) || null,
              authorName: sharedAuthorName,
              videoTitle: sharedVideoTitle,
              publishDate: sharedPublishDate,
              thumbnailUrl: sharedThumbnailUrl
            });
          }
        }
      }

      for (const nestedValue of Object.values(value)) {
        visit(nestedValue, depth + 1);
      }
    }

    visit(root, 0);
    return candidates;
  }

  async function sendCandidates(candidates) {
    if (!candidates.length) {
      return;
    }
    await safeSendMessage({
      target: "background",
      action: "PAGE_CANDIDATES",
      candidates
    }).catch(() => {});
  }

  async function sendPageContext() {
    await safeSendMessage({
      target: "background",
      action: "PAGE_CONTEXT",
      pageContext: getPageContext()
    }).catch(() => {});
  }

  function handleWindowMessage(event) {
    if (!extensionContextAlive) {
      return;
    }
    if (event.source !== window || !event.data || event.data.source !== HOOK_SOURCE) {
      return;
    }

    if (event.data.type === "NETWORK_CANDIDATES") {
      const candidates = extractCandidatesFromObject(event.data.payload);
      sendCandidates(candidates);
      return;
    }

    const directUrl = event.data.url || (event.data.payload && event.data.payload.url);
    if (event.data.type === "DIRECT_MEDIA_URL" && typeof directUrl === "string") {
      sendCandidates([
        {
          url: directUrl,
          source: "hook"
        }
      ]);
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!extensionContextAlive) {
      sendResponse({ ok: false, error: "inactive" });
      return false;
    }
    if (message.action === "RESCAN_DOM") {
      Promise.all([
        sendCandidates(scanDomForCandidates()),
        sendPageContext()
      ]).finally(() => sendResponse({ ok: true }));
      return true;
    }
    sendResponse({ ok: false });
    return false;
  });

  injectHook();
  window.addEventListener("message", handleWindowMessage);
  sendCandidates(scanDomForCandidates());
  sendPageContext();

  domObserver = new MutationObserver(() => {
    if (!extensionContextAlive) {
      return;
    }
    sendCandidates(scanDomForCandidates());
    sendPageContext();
  });
  domObserver.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  function handlePlaybackEvent() {
    if (!extensionContextAlive) {
      return;
    }
    sendPageContext();
  }

  document.addEventListener("play", handlePlaybackEvent, true);
  document.addEventListener("pause", handlePlaybackEvent, true);
  document.addEventListener("timeupdate", handlePlaybackEvent, true);
})();
