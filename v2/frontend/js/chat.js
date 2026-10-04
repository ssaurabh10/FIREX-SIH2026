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

  // Bold **text**
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

  // Italic *text*
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");

  // Code `code`
  html = html.replace(/`(.*?)`/g, "<code class=\"chat-inline-code\">$1</code>");

  // Highlight Incident IDs (#xxxxxxxx) into clickable tokens
  html = html.replace(/#([a-f0-9]{8}(?:-[a-f0-9]{3,})?)/gi, (match, id) => {
    return `<button class="incident-link-btn" data-incident-id="${id}" title="View target #${id.slice(0, 8)}">#${id.slice(0, 8)}</button>`;
  });

  // Convert newlines to paragraphs / line breaks
  const paragraphs = html.split(/\n\n+/);
  return paragraphs
    .map(p => {
      const lines = p.split(/\n/);
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

    msgDiv.appendChild(bubble);
    msgDiv.appendChild(meta);
    body.appendChild(msgDiv);
    scrollToBottom();

    // Wire up any incident buttons
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
      const reply = data.reply || data.response || "I received your message. Let me know if you have any questions about fire monitoring or the prototype.";

      appendMessage("bot", reply);
    } catch (err) {
      removeTypingIndicator();
      console.warn("[FIREX Assistant] Chat error:", err);
      const fallbackReply = generateOfflineReport(text);
      appendMessage("bot", fallbackReply);
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
    const q = query.toLowerCase().trim();
    const tokens = q.split(/\s+/).map(w => w.replace(/[^a-z0-9]/g, ""));
    const greetings = ["hi", "hello", "hey", "hii", "heyy", "namaste", "hola", "yo"];

    if (tokens.some(t => greetings.includes(t)) && tokens.length <= 3) {
      return "Hello! How can I help you today? You can ask me about current fire hotspots across India, our detection pipeline, or how we prevent false alarms.";
    }
    if (q.includes("how are you")) {
      return "I'm doing well, thank you! Ready to help you with any questions about fire monitoring or the FIREX platform.";
    }
    if (q.includes("who are you") || q.includes("what are you")) {
      return "I'm the FIREX Assistant, an AI helper for India's thermal anomaly and wildfire monitoring platform. I can explain our detection system, active hotspots, and false-alarm suppression.";
    }
    if (q.includes("thank")) {
      return "You're very welcome! Let me know if you have any other questions.";
    }
    if (q.includes("gujarat") || q.includes("refinery") || q.includes("jamnagar")) {
      return "In Gujarat, detected hotspots around Jamnagar and Vadodara correspond to monitored petroleum refineries and industrial flares, which are operating within expected baseline limits.";
    }
    if (q.includes("punjab") || q.includes("crop") || q.includes("agriculture")) {
      return "Hotspots detected in Punjab are seasonal agricultural residue burns from stubble clearing, with fire radiative power usually between 10 and 35 MW.";
    }
    if (q.includes("surge") || q.includes("critical") || q.includes("biggest") || q.includes("top")) {
      return "Currently, active hotspots across India are monitored for surges. An anomaly is flagged as a critical surge when its heat output spikes to more than 2.5 times its historical 365-day baseline.";
    }
    if (q.includes("false alarm") || q.includes("avoid")) {
      return "We avoid false alarms using a 365-day historical baseline for every coordinate in India. If a known factory or flare stack operates within its expected heat range, it is marked as routine.";
    }
    if (q.includes("how") || q.includes("detect")) {
      return "FIREX takes live NASA VIIRS satellite data over India twice daily, compares the heat with 365-day historical baselines, checks nearby industrial assets, and verifies images with AI vision.";
    }
    return "FIREX monitors thermal anomalies across India using satellite data and historical baselines. Feel free to ask how our detection works or about specific regions.";
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
