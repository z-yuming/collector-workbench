(function () {
  const HOOK_SOURCE = "__media_catcher_hook__";
  const seenPerformanceUrls = new Set();

  function emit(type, payload) {
    window.postMessage({
      source: HOOK_SOURCE,
      type,
      payload
    }, "*");
  }

  function looksInterestingUrl(url) {
    const lowered = String(url || "").toLowerCase();
    return (
      lowered.includes("/api/") ||
      lowered.includes("/aweme/") ||
      lowered.includes("/graphql") ||
      lowered.includes("/feed") ||
      lowered.includes(".json") ||
      lowered.includes("playaddr") ||
      lowered.includes("playapi") ||
      lowered.includes(".m3u8") ||
      lowered.includes(".mp4")
    );
  }

  function parseMaybeJson(text) {
    try {
      return JSON.parse(text);
    } catch (_error) {
      return null;
    }
  }

  function emitDirectUrl(url, transport) {
    if (!url || !looksInterestingUrl(url)) {
      return;
    }
    emit("DIRECT_MEDIA_URL", { transport, url });
  }

  function scanPerformanceEntries() {
    try {
      const entries = performance.getEntriesByType("resource");
      for (const entry of entries.slice(-200)) {
        const url = entry && entry.name ? String(entry.name) : "";
        if (!url || seenPerformanceUrls.has(url) || !looksInterestingUrl(url)) {
          continue;
        }
        seenPerformanceUrls.add(url);
        emitDirectUrl(url, "performance");
      }
    } catch (_error) {
      // Ignore performance access failures.
    }
  }

  const originalFetch = window.fetch;
  window.fetch = async function patchedFetch(...args) {
    const response = await originalFetch.apply(this, args);
    try {
      const url = response.url || String(args[0] || "");
      if (looksInterestingUrl(url)) {
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          response.clone().json().then((data) => {
            emit("NETWORK_CANDIDATES", {
              transport: "fetch",
              url,
              response: data
              });
          }).catch(() => {});
        } else if (url.includes(".m3u8") || url.includes(".mp4")) {
          emitDirectUrl(url, "fetch");
        } else if (contentType.includes("text/plain")) {
          response.clone().text().then((text) => {
            const parsed = parseMaybeJson(text);
            if (parsed) {
              emit("NETWORK_CANDIDATES", {
                transport: "fetch",
                url,
                response: parsed
              });
            }
          }).catch(() => {});
        }
      }
    } catch (_error) {
      // Ignore hook failures to avoid breaking page fetches.
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function patchedOpen(method, url) {
    this.__mediaCatcherUrl = url;
    return originalOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function patchedSend() {
    this.addEventListener("load", function onLoad() {
      try {
        const url = this.responseURL || this.__mediaCatcherUrl || "";
        if (!looksInterestingUrl(url)) {
          return;
        }
        if (url.includes(".m3u8") || url.includes(".mp4")) {
          emitDirectUrl(url, "xhr");
          return;
        }
        if (this.responseType === "" || this.responseType === "text") {
          const parsed = parseMaybeJson(this.responseText);
          if (parsed) {
            emit("NETWORK_CANDIDATES", {
              transport: "xhr",
              url,
              response: parsed
            });
          }
        }
      } catch (_error) {
        // Ignore hook failures to avoid breaking page XHR.
      }
    });
    return originalSend.apply(this, arguments);
  };

  scanPerformanceEntries();
  setInterval(scanPerformanceEntries, 2000);
})();
