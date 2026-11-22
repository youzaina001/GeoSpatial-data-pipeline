import {
  buildReproduceInfo,
  filterAndSortPages,
  isAllowedArchiveUrl,
  validateAttributionLink,
  validateComparisonPayload,
} from "./lib.js";

const NUMBER_FORMAT = new Intl.NumberFormat("en-US");

function formatInteger(value) {
  return NUMBER_FORMAT.format(value);
}

function getRequiredElement(selector) {
  const element = document.querySelector(selector);
  if (!element) {
    throw new Error(`Missing required DOM element: ${selector}`);
  }
  return element;
}

function createExternalLink(href, text) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = text;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function createStatusBadge(page) {
  const badge = document.createElement("span");
  if (page.status === "compared") {
    badge.className = "badge badge-compared";
    badge.textContent = `${formatInteger(page.new_words)} words`;
  } else {
    badge.className = "badge badge-incomplete";
    badge.textContent = "Incomplete";
  }
  return badge;
}

function createCaptureSlot(label, captureUrl, archiveHost) {
  const slot = document.createElement("div");
  slot.className = "capture-slot";

  const dt = document.createElement("dt");
  dt.textContent = label;
  slot.appendChild(dt);

  const dd = document.createElement("dd");
  if (captureUrl === null) {
    const empty = document.createElement("span");
    empty.className = "capture-empty";
    empty.textContent = "Not captured";
    dd.appendChild(empty);
  } else if (isAllowedArchiveUrl(captureUrl, archiveHost)) {
    dd.appendChild(createExternalLink(captureUrl, "Open archived capture"));
  } else {
    const fallback = document.createElement("span");
    fallback.className = "capture-fallback";
    fallback.setAttribute("data-capture-fallback", "");
    fallback.textContent = "Capture link unavailable";
    dd.appendChild(fallback);
  }
  slot.appendChild(dd);
  return slot;
}

function createAttributionRow(label, contentNode) {
  const row = document.createElement("div");
  row.className = "attribution-row";

  const dt = document.createElement("dt");
  dt.textContent = label;
  row.appendChild(dt);

  const dd = document.createElement("dd");
  dd.appendChild(contentNode);
  row.appendChild(dd);
  return row;
}

function renderSummary(comparison) {
  const samplePill = getRequiredElement("[data-sample-id]");
  samplePill.textContent = comparison.sample_id;
  samplePill.hidden = false;

  getRequiredElement("[data-window-range]").textContent =
    `${comparison.earlier_window} -> ${comparison.later_window}`;
  getRequiredElement("[data-summary-words]").textContent = formatInteger(
    comparison.summary.distinct_new_words,
  );
  getRequiredElement("[data-compared-count]").textContent = formatInteger(
    comparison.summary.compared_pages,
  );
  getRequiredElement("[data-excluded-count]").textContent = formatInteger(
    comparison.summary.excluded_pages,
  );

  const reproduceInfo = buildReproduceInfo(comparison);
  const reproduceLink = getRequiredElement("[data-reproduce-link]");
  reproduceLink.href = reproduceInfo.treeUrl;

  getRequiredElement("[data-producing-commit]").textContent = comparison.producing_commit;
  getRequiredElement("[data-manifest-sha256]").textContent = comparison.manifest_sha256;
  getRequiredElement("[data-demo-command]").textContent = reproduceInfo.demoCommand;

  const manifestSlot = getRequiredElement("[data-manifest-slot]");
  if (reproduceInfo.manifestUrl) {
    manifestSlot.replaceChildren(
      createExternalLink(
        reproduceInfo.manifestUrl,
        `fixtures/${comparison.sample_id}/manifest.json`,
      ),
    );
  } else {
    manifestSlot.textContent = "Manifest link unavailable for this sample ID";
  }

  getRequiredElement("[data-comparison-shell]").hidden = false;
  getRequiredElement("[data-pages-shell]").hidden = false;
}

function renderAttribution(attribution) {
  const footer = getRequiredElement("[data-attribution-footer]");
  const list = getRequiredElement("[data-attribution-list]");

  if (!attribution) {
    footer.hidden = true;
    list.replaceChildren();
    return;
  }

  const rows = [];

  if (validateAttributionLink(attribution.license_url)) {
    rows.push(
      createAttributionRow("License", createExternalLink(attribution.license_url, attribution.license)),
    );
  } else {
    rows.push(createAttributionRow("License", document.createTextNode(attribution.license)));
  }

  rows.push(createAttributionRow("Authors", document.createTextNode(attribution.authors)));

  if (validateAttributionLink(attribution.source_url)) {
    rows.push(
      createAttributionRow("Source", createExternalLink(attribution.source_url, attribution.source_url)),
    );
  } else {
    rows.push(createAttributionRow("Source", document.createTextNode(attribution.source_url)));
  }

  rows.push(
    createAttributionRow("Modifications", document.createTextNode(attribution.modifications)),
  );

  list.replaceChildren(...rows);
  footer.hidden = false;
}

function renderPageDetail(page, comparison) {
  const detailBody = getRequiredElement("[data-detail-body]");

  if (!page) {
    const empty = document.createElement("p");
    empty.className = "detail-empty";
    empty.textContent = "No page selected. Adjust the search or status filter to inspect a page.";
    detailBody.replaceChildren(empty);
    return;
  }

  const urlParagraph = document.createElement("p");
  urlParagraph.className = "detail-url";
  urlParagraph.textContent = page.url;

  const metrics = document.createElement("div");
  metrics.className = "detail-metrics";

  const wordCount = document.createElement("span");
  wordCount.className = "detail-word-count";
  if (page.status === "compared") {
    wordCount.textContent = `${formatInteger(page.new_words)} new words`;
  } else {
    wordCount.textContent = "Comparison incomplete";
  }
  metrics.appendChild(wordCount);

  const statusPill = document.createElement("span");
  statusPill.className =
    page.status === "compared" ? "badge badge-compared" : "badge badge-incomplete";
  statusPill.textContent = page.status === "compared" ? "Compared" : "Comparison incomplete";
  metrics.appendChild(statusPill);

  const captures = document.createElement("dl");
  captures.className = "captures-grid";
  captures.appendChild(
    createCaptureSlot(
      `Earlier capture (${comparison.earlier_window})`,
      page.earlier_capture_url,
      comparison.archive_host,
    ),
  );
  captures.appendChild(
    createCaptureSlot(
      `Later capture (${comparison.later_window})`,
      page.later_capture_url,
      comparison.archive_host,
    ),
  );

  detailBody.replaceChildren(urlParagraph, metrics, captures);
}

function showError(title, message) {
  getRequiredElement("[data-loading-status]").textContent = "Failed to load comparison.";
  getRequiredElement("[data-error-title]").textContent = title;
  getRequiredElement("[data-error-message]").textContent = message;
  getRequiredElement("[data-error-banner]").hidden = false;
  getRequiredElement("[data-comparison-shell]").hidden = true;
  getRequiredElement("[data-pages-shell]").hidden = true;
  getRequiredElement("[data-attribution-footer]").hidden = true;
}

function mountExplorer(comparison) {
  const state = {
    query: "",
    statusFilter: "all",
    sortBy: "new_words_desc",
    selectedUrl: null,
  };

  const urlFilterInput = getRequiredElement("[data-url-filter]");
  const sortSelect = getRequiredElement("[data-sort-select]");
  const statusButtons = Array.from(document.querySelectorAll("[data-status-filter]"));
  const pageList = getRequiredElement("[data-page-list]");
  const emptyListMessage = getRequiredElement("[data-empty-list]");
  const matchCount = getRequiredElement("[data-match-count]");

  function updateView({ restoreFocus = false } = {}) {
    const filtered = filterAndSortPages(comparison.pages, {
      query: state.query,
      statusFilter: state.statusFilter,
      sortBy: state.sortBy,
    });

    if (filtered.length === 0) {
      state.selectedUrl = null;
    } else if (!filtered.some((page) => page.url === state.selectedUrl)) {
      state.selectedUrl = filtered[0].url;
    }

    const total = comparison.pages.length;
    matchCount.textContent = `Showing ${formatInteger(filtered.length)} of ${formatInteger(total)} pages`;

    let selectedButton = null;
    const items = filtered.map((page) => {
      const li = document.createElement("li");
      li.className = "page-list-item";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "page-row";
      button.setAttribute("data-page-row", "");

      const isSelected = page.url === state.selectedUrl;
      button.setAttribute("aria-current", isSelected ? "true" : "false");
      if (isSelected) {
        selectedButton = button;
      }

      const urlSpan = document.createElement("span");
      urlSpan.className = "page-row-url";
      urlSpan.textContent = page.url;

      const metaSpan = document.createElement("span");
      metaSpan.className = "page-row-meta";
      metaSpan.appendChild(createStatusBadge(page));

      button.append(urlSpan, metaSpan);
      button.addEventListener("click", () => {
        state.selectedUrl = page.url;
        updateView({ restoreFocus: true });
      });

      li.appendChild(button);
      return li;
    });

    pageList.replaceChildren(...items);
    emptyListMessage.hidden = filtered.length > 0;

    if (restoreFocus && selectedButton) {
      selectedButton.focus();
    }

    const selectedPage = filtered.find((page) => page.url === state.selectedUrl) ?? null;
    renderPageDetail(selectedPage, comparison);
  }

  urlFilterInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    updateView();
  });

  sortSelect.addEventListener("change", (event) => {
    state.sortBy = event.target.value;
    updateView();
  });

  for (const button of statusButtons) {
    button.addEventListener("click", () => {
      const nextStatus = button.getAttribute("data-status-filter") || "all";
      state.statusFilter = nextStatus;
      for (const btn of statusButtons) {
        btn.setAttribute("aria-pressed", btn === button ? "true" : "false");
      }
      updateView();
    });
  }

  renderSummary(comparison);
  renderAttribution(comparison.attribution);
  updateView();

  getRequiredElement("[data-loading-status]").textContent =
    `Loaded ${comparison.sample_id} (${comparison.earlier_window} to ${comparison.later_window}).`;
}

async function init() {
  let response;
  try {
    response = await fetch("./comparison.json", { cache: "no-store" });
  } catch (error) {
    showError(
      "Could not fetch ./comparison.json",
      `Serve explorer/ over HTTP with a comparison.json file alongside index.html (for example, run "make demo"). Details: ${error instanceof Error ? error.message : String(error)}`,
    );
    return;
  }

  if (!response.ok) {
    showError(
      `Could not load ./comparison.json (HTTP ${response.status})`,
      "Place a valid comparison.json file next to index.html, or run \"make demo\" to generate a local sample.",
    );
    return;
  }

  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    showError(
      "comparison.json is not valid JSON",
      `Failed to parse comparison.json: ${error instanceof Error ? error.message : String(error)}`,
    );
    return;
  }

  let comparison;
  try {
    comparison = validateComparisonPayload(payload);
  } catch (error) {
    showError(
      "comparison.json failed schema validation",
      error instanceof Error ? error.message : String(error),
    );
    return;
  }

  mountExplorer(comparison);
}

init();
