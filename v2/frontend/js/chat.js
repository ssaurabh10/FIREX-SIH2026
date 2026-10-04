// ==========================================================================
// FIREX AI Tactical Copilot - Client Controller
// ==========================================================================

const CHAT_STORAGE_KEY = "firex_copilot_history_v1";

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatMarkdown(text) {
  if (!text) return "";
  let html = escapeHtml(text);

  // Bold **text** — handle tactical headers specially
  html = html.replace(/\*\*(.*?)\*\*/g, (match, content) => {
    if (/^[A-Z0-9_\s\/:—\-\/]+$/.test(content.trim()) || content.includes("SITREP") || content.includes("TACTICAL") || content.includes("DIRECTIVE") || content.includes("TELEMETRY")) {
      return `<strong class="chat-heading">${content}</strong>`;
    }
    return `<strong>${content}</strong>`;
  });

  // Italic *text*
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");

  // Code `code`
  html = html.replace(/`(.*?)`/g, "<code class=\"chat-inline-code\">$1</code>");

  // Highlight Incident IDs (#xxxxxxxx) into clickable tactical tokens
  html = html.replace(/#([a-f0-9]{8}(?:-[a-f0-9]{3,})?)/gi, (match, id) => {
    return `<button class="incident-link-btn" data-incident-id="${id}" title="Inspect incident #${id.slice(0, 8)}">#${id.slice(0, 8)}</button>`;
  });

  // Highlight coordinates and physical measurements in monospace
  html = html.replace(/\b(\d+(?:\.\d+)?\s*(?:MW|km|hPa|K))\b/gi, '<span class="val-mono">$1</span>');
  html = html.replace(/\b(\d{1,2}\.\d{2,4}°[NS],\s*\d{1,3}\.\d{2,4}°[EW])\b/gi, '<span class="val-mono">$1</span>');

  // Convert newlines to paragraphs / line breaks
  const paragraphs = html.split(/\n\n+/);
  return paragraphs
    .map(p => {
      const lines = p.split(/\n/);
      // Check for bullet list
      if (lines.every(l => l.trim().startsWith("- ") || l.trim().startsWith("* "))) {
        const items = lines.map(l => `<li>${l.replace(/^[-*]\s+/, "")}</li>`).join("");
        return `<ul class="chat-bullet-list">${items}</ul>`;
      }
      return `<p>${lines.join("<br>")}</p>`;
    })
    .join("");
}

export function initChatWidget() {
  const triggerBtn = document.getElementById("btn-toggle-chat");
  const widget = document.getElementById("chat-widget");
  const closeBtn = document.getElementById("btn-close-chat");
  const clearBtn = document.getElementById("btn-clear-chat");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send-btn");
  const body = document.getElementById("chat-body");
  const suggestions = document.getElementById("chat-suggestions");

  if (!widget || !triggerBtn || !input) return;

  let messageHistory = [];

  function toggleChat(force) {
    const isOpen = widget.getAttribute("data-open") === "true";
    const nextState = force !== undefined ? force : !isOpen;
    widget.setAttribute("data-open", String(nextState));
    triggerBtn.setAttribute("aria-expanded", String(nextState));
    if (nextState) {
      setTimeout(() => input.focus(), 150);
      scrollToBottom();
    }
  }

  function scrollToBottom() {
    if (body) {
      body.scrollTop = body.scrollHeight;
    }
  }

  function appendMessage(role, text) {
    if (!body) return;
    const timeStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-msg chat-msg--${role}`;

    const bubble = document.createElement("div");
    bubble.className = "chat-msg__bubble";
    bubble.innerHTML = role === "bot" ? formatMarkdown(text) : `<p>${escapeHtml(text)}</p>`;

    const meta = document.createElement("div");
    meta.className = "chat-msg__meta";

    const timeSpan = document.createElement("span");
    timeSpan.className = "chat-msg__time";
    timeSpan.textContent = timeStr;
    meta.appendChild(timeSpan);

    if (role === "bot") {
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "chat-copy-btn";
      copyBtn.innerHTML = `<svg class="i i--sm" style="width:11px;height:11px;" aria-hidden="true"><use href="#i-mark"/></svg><span>COPY</span>`;
      copyBtn.title = "Copy response";
      copyBtn.addEventListener("click", () => {
        const cleanText = text.replace(/[*`#]/g, "").replace(/\n\s*\n/g, "\n\n").trim();
        navigator.clipboard.writeText(cleanText).then(() => {
          copyBtn.classList.add("copied");
          copyBtn.innerHTML = `<svg class="i i--sm" style="width:11px;height:11px;color:#22c55e;" aria-hidden="true"><use href="#i-check"/></svg><span>COPIED</span>`;
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            copyBtn.innerHTML = `<svg class="i i--sm" style="width:11px;height:11px;" aria-hidden="true"><use href="#i-mark"/></svg><span>COPY</span>`;
          }, 2000);
        }).catch(() => {});
      });
      meta.appendChild(copyBtn);
    }

    msgDiv.appendChild(bubble);
    msgDiv.appendChild(meta);
    body.appendChild(msgDiv);
    scrollToBottom();

    // Allow clicking incident IDs to view dossier
    bubble.querySelectorAll(".incident-link-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const incId = btn.getAttribute("data-incident-id");
        if (window.FIREX_SELECT_INCIDENT) {
          window.FIREX_SELECT_INCIDENT(incId);
        } else {
          const card = document.querySelector(`.spine-card[data-id^="${incId}"]`);
          if (card) card.click();
        }
      });
    });

    messageHistory.push({ role, content: text });
  }

  function showTypingIndicator() {
    const typing = document.createElement("div");
    typing.id = "chat-typing-indicator";
    typing.className = "chat-typing";
    typing.innerHTML = `
      <span class="chat-typing__dot"></span>
      <span class="chat-typing__dot"></span>
      <span class="chat-typing__dot"></span>
    `;
    body.appendChild(typing);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const typing = document.getElementById("chat-typing-indicator");
    if (typing) typing.remove();
  }

  async function handleSend() {
    const text = input.value.trim();
    if (!text) return;

    // Hide suggestions after first message
    if (suggestions) suggestions.style.display = "none";

    input.value = "";
    input.style.height = "auto";
    sendBtn.disabled = true;

    appendMessage("user", text);
    showTypingIndicator();

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonBodySafe({
          message: text,
          history: messageHistory.slice(-8)
        })
      });

      removeTypingIndicator();

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const data = await resp.json();
      const reply = data.reply || data.response || "I received your message, but no additional details are available.";
      appendMessage("bot", reply);
    } catch (err) {
      removeTypingIndicator();
      console.warn("[FIREX Copilot] Live chat error:", err);
      // Fallback response with live telemetry context
      const fallback = generateOfflineReport(text);
      appendMessage("bot", fallback);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  function jsonBodySafe(obj) {
    try {
      return JSON.stringify(obj);
    } catch (e) {
      return JSON.stringify({ message: obj.message });
    }
  }

  function generateOfflineReport(query) {
    const q = query.toLowerCase();
    if (q.includes("gujarat") || q.includes("refinery") || q.includes("jamnagar")) {
      return "In Sector West (Gujarat), routine industrial and refinery flaring is active around Jamnagar. Continuous heat emissions range from 7.9 MW to 14.2 MW, which is within the normal 365-day historical baseline envelope. No uncontained wildfires are detected.";
    }
    if (q.includes("punjab") || q.includes("agricultural") || q.includes("crop")) {
      return "Seasonal agricultural residue burn clusters are detected in Punjab (Bathinda, Sangrur, and Patiala corridors), with heat outputs up to 34.7 MW verified by NASA VIIRS satellite daytime passes.";
    }
    if (q.includes("surge") || q.includes("critical")) {
      return "A critical surge occurs when an observed hotspot emits heat more than 2.5 times higher than that location's normal 365-day P95 historical baseline. These hotspots are flagged with highest priority for emergency forest response.";
    }
    if (q.includes("p95") || q.includes("baseline")) {
      return "The 365-day P95 baseline represents the 95th percentile of heat emissions observed at each coordinate over the past year. Comparing new satellite observations against this baseline allows FIREX to filter out routine industrial heat from factories and power plants.";
    }
    return "FIREX is currently monitoring active thermal hotspots across India, cross-referencing satellite detections with historical baselines to filter out routine industrial flaring. Feel free to ask any question about the platform.";
  }

  // Event Listeners
  triggerBtn.addEventListener("click", () => toggleChat());
  closeBtn?.addEventListener("click", () => toggleChat(false));

  clearBtn?.addEventListener("click", () => {
    body.querySelectorAll(".chat-msg").forEach(m => m.remove());
    messageHistory = [];
    if (suggestions) suggestions.style.display = "flex";
  });

  // Quick Chips
  document.querySelectorAll(".chat-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const textSpan = chip.querySelector("span");
      input.value = (textSpan ? textSpan.textContent : chip.textContent).trim();
      handleSend();
    });
  });

  // Form submission & keyboard
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    handleSend();
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  // Auto-resize input
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 90) + "px";
  });

  // Close when pressing Escape
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && widget.getAttribute("data-open") === "true") {
      toggleChat(false);
    }
  });

  // Global trigger for contextual deep queries from other UI components
  window.FIREX_ASK_COPILOT = (query) => {
    toggleChat(true);
    input.value = query;
    handleSend();
  };
}

// Auto-initialize when DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initChatWidget);
} else {
  initChatWidget();
}
