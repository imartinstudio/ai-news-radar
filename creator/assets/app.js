const DATA_URL = "../data/creator-editions.json";

const state = {
  editions: [],
  editionFilter: "all",
  statusFilter: "all",
};

const STATUS_META = {
  confirmed: ["已确认", "status-confirmed"],
  single_source: ["单一来源", "status-single"],
  early_signal: ["早期信号", "status-signal"],
  rumor: ["待确认", "status-rumor"],
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function formatEditionTitle(edition) {
  const label = edition.edition_kind === "evening" ? "晚报" : "早报";
  const date = String(edition.edition_id || "").replace(/-(morning|evening)$/, "");
  return `${date} · ${label}`;
}

function formatUpdatedAt(value) {
  if (!value) return "更新时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更新时间未知";
  return `更新于 ${new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(date)}`;
}

function statusBadge(status) {
  const [label, className] = STATUS_META[status] || ["未分类", "status-single"];
  return `<span class="status-badge ${className}">${escapeHtml(label)}</span>`;
}

function renderAngles(angles) {
  if (!Array.isArray(angles) || !angles.length) return "";
  const rows = angles.slice(0, 3).map((angle) => {
    const platform = {
      x: "X",
      xiaohongshu: "小红书",
      wechat: "公众号",
    }[angle.platform] || "选题";
    return `
      <li>
        <span class="platform-tag">${escapeHtml(platform)}</span>
        <div>
          <strong>${escapeHtml(angle.title)}</strong>
          <p>${escapeHtml(angle.angle)}</p>
        </div>
      </li>`;
  }).join("");
  return `<div class="angles"><h4>内容角度</h4><ul>${rows}</ul></div>`;
}

function renderItem(item) {
  const sourceUrl = safeUrl(item.url || item.primary_url);
  const title = escapeHtml(item.title || "未命名资讯");
  const titleMarkup = sourceUrl
    ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${title}</a>`
    : title;
  const score = Number.isFinite(Number(item.creator_score))
    ? `<span class="score">${escapeHtml(item.creator_score)} 分</span>`
    : "";
  const change = item.change_type === "confirmed"
    ? '<span class="change-tag">由信号转为确认</span>'
    : item.change_type === "updated"
      ? '<span class="change-tag">有新进展</span>'
      : "";

  return `
    <article class="story-card">
      <div class="story-topline">
        ${statusBadge(item.verification_status)}
        ${score}
        ${change}
      </div>
      <h3>${titleMarkup}</h3>
      <p class="summary">${escapeHtml(item.summary_zh || "暂无摘要")}</p>
      <div class="why">
        <span>为什么重要</span>
        <p>${escapeHtml(item.why_it_matters || "暂无影响判断")}</p>
      </div>
      ${renderAngles(item.angles)}
    </article>`;
}

function filteredItems(edition) {
  const items = Array.isArray(edition.items) ? edition.items : [];
  if (state.statusFilter === "all") return items;
  return items.filter((item) => item.verification_status === state.statusFilter);
}

function render() {
  const root = document.getElementById("editionList");
  const editions = state.editions.filter((edition) => (
    state.editionFilter === "all" || edition.edition_kind === state.editionFilter
  ));

  const markup = editions.map((edition) => {
    const items = filteredItems(edition);
    if (!items.length) return "";
    return `
      <section class="edition-block">
        <header class="edition-header">
          <div>
            <p class="edition-kicker">${escapeHtml(edition.edition_kind === "evening" ? "EVENING" : "MORNING")}</p>
            <h2>${escapeHtml(formatEditionTitle(edition))}</h2>
          </div>
          <span>${items.length} 条</span>
        </header>
        <div class="story-grid">${items.map(renderItem).join("")}</div>
      </section>`;
  }).filter(Boolean).join("");

  root.innerHTML = markup || '<div class="empty-card">当前筛选条件下没有内容。</div>';
}

async function load() {
  const root = document.getElementById("editionList");
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.editions = Array.isArray(payload.editions) ? payload.editions : [];
    document.getElementById("updatedAt").textContent = formatUpdatedAt(payload.generated_at);
    render();
  } catch (error) {
    root.innerHTML = `<div class="error-card">情报数据暂时不可用：${escapeHtml(error.message)}</div>`;
    document.getElementById("updatedAt").textContent = "数据加载失败";
  }
}

document.getElementById("editionFilter").addEventListener("change", (event) => {
  state.editionFilter = event.target.value;
  render();
});

document.getElementById("statusFilter").addEventListener("change", (event) => {
  state.statusFilter = event.target.value;
  render();
});

load();
