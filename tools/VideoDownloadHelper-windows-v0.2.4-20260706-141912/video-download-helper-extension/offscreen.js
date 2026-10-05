function sanitizeFilenamePart(text) {
  return String(text || "download")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "download";
}

function extensionFromUrl(url) {
  try {
    const pathname = new URL(url).pathname.toLowerCase();
    const match = pathname.match(/\.([a-z0-9]{2,5})$/);
    return match ? `.${match[1]}` : "";
  } catch (_error) {
    return "";
  }
}

function buildMediaFilenameBase(media) {
  const authorName = String(media.authorName || "").trim();
  const publishDate = String(media.publishDate || "").trim();
  if (authorName && publishDate) {
    return sanitizeFilenamePart(`${authorName}_${publishDate}`);
  }
  if (authorName) {
    return sanitizeFilenamePart(authorName);
  }
  if (publishDate) {
    return sanitizeFilenamePart(publishDate);
  }
  return sanitizeFilenamePart(media.pageTitle || media.title || media.kind || "media");
}

function guessFilename(media, forcedExt = "") {
  const base = buildMediaFilenameBase(media);
  const ext = forcedExt || extensionFromUrl(media.url) || (media.kind === "audio" ? ".mp3" : ".mp4");
  return `${base}${ext}`;
}

function absolutizeUrl(baseUrl, maybeRelativeUrl) {
  return new URL(maybeRelativeUrl, baseUrl).toString();
}

async function reportProgress(jobId, status, progress, message = "") {
  await chrome.runtime.sendMessage({
    target: "background",
    action: "OFFSCREEN_DOWNLOAD_PROGRESS",
    jobId,
    status,
    progress,
    message
  }).catch(() => {});
}

async function reportDone(jobId, ok, message = "") {
  await chrome.runtime.sendMessage({
    target: "background",
    action: "OFFSCREEN_DOWNLOAD_DONE",
    jobId,
    ok,
    message
  }).catch(() => {});
}

function triggerDownload(blob, filename) {
  const link = document.createElement("a");
  const objectUrl = URL.createObjectURL(blob);
  link.href = objectUrl;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

function normalizeRequestHeaders(headers) {
  const result = {};
  for (const [name, value] of Object.entries(headers || {})) {
    const normalizedName = String(name || "").toLowerCase();
    if (!normalizedName || value == null) {
      continue;
    }
    if (normalizedName === "range") {
      continue;
    }
    result[normalizedName] = value;
  }
  return result;
}

async function fetchWithHeaders(url, headers, onProgress) {
  const response = await fetch(url, { headers: normalizeRequestHeaders(headers) });
  if (!response.ok) {
    throw new Error(`Fetch failed: ${response.status} ${response.statusText}`);
  }

  if (!response.body) {
    const blob = await response.blob();
    if (onProgress) {
      onProgress(blob.size, blob.size);
    }
    return {
      contentType: response.headers.get("content-type") || "",
      blob
    };
  }

  const total = Number.parseInt(response.headers.get("content-length") || "0", 10) || 0;
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    chunks.push(value);
    loaded += value.byteLength;
    if (onProgress) {
      onProgress(loaded, total);
    }
  }

  return {
    contentType: response.headers.get("content-type") || "",
    blob: new Blob(chunks, {
      type: response.headers.get("content-type") || "application/octet-stream"
    })
  };
}

function parseM3u8Segments(manifestText, manifestUrl) {
  const lines = manifestText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const segments = [];
  for (const line of lines) {
    if (line.startsWith("#")) {
      continue;
    }
    segments.push(absolutizeUrl(manifestUrl, line));
  }
  return segments;
}

async function downloadStandardMedia(jobId, media) {
  await reportProgress(jobId, "downloading", 1, "开始拉取文件");
  const result = await fetchWithHeaders(media.url, media.requestHeaders, (loaded, total) => {
    const progress = total > 0 ? Math.min(99, Math.round((loaded / total) * 100)) : 0;
    reportProgress(jobId, "downloading", progress, total > 0 ? `已下载 ${loaded}/${total} 字节` : `已下载 ${loaded} 字节`);
  });

  const ext = extensionFromUrl(media.url) || (
    result.contentType.includes("webm") ? ".webm" :
    result.contentType.includes("quicktime") ? ".mov" :
    result.contentType.startsWith("audio/") ? ".mp3" :
    ".mp4"
  );

  triggerDownload(result.blob, guessFilename(media, ext));
  await reportDone(jobId, true, "下载完成");
}

async function downloadM3u8(jobId, media) {
  await reportProgress(jobId, "downloading", 1, "开始拉取播放清单");
  const requestHeaders = normalizeRequestHeaders(media.requestHeaders);
  const response = await fetch(media.url, { headers: requestHeaders });
  if (!response.ok) {
    throw new Error(`Playlist fetch failed: ${response.status} ${response.statusText}`);
  }
  const manifestText = await response.text();

  if (/#EXT-X-KEY/i.test(manifestText)) {
    triggerDownload(new Blob([manifestText], { type: "application/vnd.apple.mpegurl" }), guessFilename(media, ".m3u8"));
    await reportDone(jobId, true, "检测到加密清单，已保存原始 m3u8 文件");
    return;
  }

  const segments = parseM3u8Segments(manifestText, media.url);
  if (!segments.length) {
    triggerDownload(new Blob([manifestText], { type: "application/vnd.apple.mpegurl" }), guessFilename(media, ".m3u8"));
    await reportDone(jobId, true, "未识别到分片，已保存原始 m3u8 文件");
    return;
  }

  const parts = [];
  let totalBytes = 0;

  for (let index = 0; index < segments.length; index += 1) {
    const segmentUrl = segments[index];
    const segmentResponse = await fetch(segmentUrl, { headers: requestHeaders });
    if (!segmentResponse.ok) {
      throw new Error(`Segment fetch failed: ${segmentResponse.status} ${segmentResponse.statusText}`);
    }
    const chunk = new Uint8Array(await segmentResponse.arrayBuffer());
    totalBytes += chunk.byteLength;
    parts.push(chunk);
    const progress = Math.round(((index + 1) / segments.length) * 100);
    await reportProgress(jobId, "downloading", progress, `已完成 ${index + 1}/${segments.length} 个分片`);
  }

  const merged = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of parts) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }

  triggerDownload(new Blob([merged.buffer], { type: "video/mp2t" }), guessFilename(media, ".ts"));
  await reportDone(jobId, true, "m3u8 分片已合并为 ts 文件");
}

function captureFrame(video) {
  if (!video.videoWidth || !video.videoHeight) {
    return "";
  }

  const canvas = document.createElement("canvas");
  const targetWidth = Math.min(320, video.videoWidth);
  const targetHeight = Math.max(1, Math.round(targetWidth * (video.videoHeight / video.videoWidth)));
  canvas.width = targetWidth;
  canvas.height = targetHeight;

  const context = canvas.getContext("2d");
  if (!context) {
    return "";
  }

  context.drawImage(video, 0, 0, targetWidth, targetHeight);
  return canvas.toDataURL("image/jpeg", 0.82);
}

async function probeVideoMetadata(url) {
  const video = document.createElement("video");
  video.preload = "metadata";
  video.crossOrigin = "anonymous";
  video.muted = true;
  video.playsInline = true;

  return await new Promise((resolve, reject) => {
    let settled = false;
    let waitingForSeek = false;
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("Metadata probe timed out"));
    }, 10000);

    function cleanup() {
      clearTimeout(timeout);
      video.onloadedmetadata = null;
      video.onloadeddata = null;
      video.onseeked = null;
      video.onerror = null;
      try {
        video.pause();
      } catch (_error) {
        // Ignore cleanup errors.
      }
      video.removeAttribute("src");
      video.load();
    }

    function finalize() {
      if (settled) {
        return;
      }
      settled = true;
      const metadata = {
        duration: Number.isFinite(video.duration) ? video.duration : null,
        width: video.videoWidth || null,
        height: video.videoHeight || null
      };

      try {
        metadata.thumbnailDataUrl = captureFrame(video);
      } catch (_error) {
        // Best-effort thumbnail only.
      }

      cleanup();
      resolve(metadata);
    }

    video.onloadedmetadata = () => {
      const targetTime = Number.isFinite(video.duration) && video.duration > 1
        ? Math.min(1, Math.max(0.2, video.duration / 3))
        : 0;

      if (targetTime > 0.05) {
        waitingForSeek = true;
        try {
          video.currentTime = targetTime;
          return;
        } catch (_error) {
          waitingForSeek = false;
        }
      }

      if (video.readyState >= 2) {
        finalize();
      }
    };

    video.onloadeddata = () => {
      if (!waitingForSeek) {
        finalize();
      }
    };

    video.onseeked = () => {
      waitingForSeek = false;
      finalize();
    };

    video.onerror = () => {
      cleanup();
      reject(new Error("Video metadata probe failed"));
    };

    video.src = url;
    video.load();
  });
}

async function probeMedia(media) {
  const metadata = {
    url: media.url,
    ...(media.thumbnailUrl ? { thumbnailUrl: media.thumbnailUrl } : {})
  };

  const headResponse = await fetch(media.url, {
    method: "HEAD",
    headers: normalizeRequestHeaders(media.requestHeaders)
  }).catch(() => null);

  if (headResponse && headResponse.ok) {
    metadata.contentType = headResponse.headers.get("content-type") || media.contentType || "";
    const length = Number.parseInt(headResponse.headers.get("content-length") || "0", 10);
    if (Number.isFinite(length) && length > 0) {
      metadata.contentLength = length;
    }
  }

  if (media.kind !== "m3u8") {
    try {
      const loaded = await probeVideoMetadata(media.url);
      Object.assign(metadata, loaded);
    } catch (_error) {
      // Best-effort probe only.
    }
  }

  return metadata;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.target !== "offscreen") {
      return;
    }

    if (message.action === "OFFSCREEN_DOWNLOAD") {
      const { jobId, media } = message;
      try {
        if (media.kind === "m3u8") {
          await downloadM3u8(jobId, media);
        } else {
          await downloadStandardMedia(jobId, media);
        }
        sendResponse({ ok: true });
      } catch (error) {
        await reportDone(jobId, false, String(error && error.message ? error.message : error));
        sendResponse({
          ok: false,
          error: String(error && error.message ? error.message : error)
        });
      }
      return;
    }

    if (message.action === "OFFSCREEN_PROBE") {
      try {
        const metadata = await probeMedia(message.media);
        sendResponse({ ok: true, metadata });
      } catch (error) {
        sendResponse({
          ok: false,
          error: String(error && error.message ? error.message : error)
        });
      }
      return;
    }

    sendResponse({ ok: false, error: "Unknown offscreen action" });
  })();

  return true;
});
