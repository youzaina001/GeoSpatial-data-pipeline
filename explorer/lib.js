// Pure browser and Node logic for the geocrawl static comparison explorer.

const DEFAULT_REPO_URL = "https://github.com/youzaina001/geocrawl";
const COMMIT_RE = /^[0-9a-f]{40}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const SAFE_SAMPLE_ID_RE = /^[a-z0-9-]+$/;
// eslint-disable-next-line no-control-regex
const DISALLOWED_URL_CHARS_RE = /[\s\x00-\x1f\x7f]/;
// eslint-disable-next-line no-control-regex
const DISALLOWED_HOST_CHARS_RE = /[\s\x00-\x1f\x7f:/?#[\]@\\]/;

const ROOT_KEYS = Object.freeze([
  "schema_version",
  "sample_id",
  "producing_commit",
  "manifest_sha256",
  "earlier_window",
  "later_window",
  "archive_host",
  "attribution",
  "summary",
  "pages",
]);
const ATTRIBUTION_KEYS = Object.freeze([
  "license",
  "license_url",
  "authors",
  "source_url",
  "modifications",
]);
const SUMMARY_KEYS = Object.freeze([
  "compared_pages",
  "excluded_pages",
  "distinct_new_words",
]);
const PAGE_KEYS = Object.freeze([
  "url",
  "status",
  "new_words",
  "earlier_capture_url",
  "later_capture_url",
]);
const VALID_STATUS_FILTERS = new Set(["all", "compared", "comparison_incomplete"]);
const VALID_SORT_MODES = new Set(["new_words_desc", "new_words_asc", "url_asc"]);

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(obj, expectedKeys) {
  const keys = Object.keys(obj);
  return (
    keys.length === expectedKeys.length &&
    expectedKeys.every((key) => Object.hasOwn(obj, key))
  );
}

function isNonNegativeInt(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function compareText(a, b) {
  if (a < b) {
    return -1;
  }
  if (a > b) {
    return 1;
  }
  return 0;
}

function parseSafeHttpUrl(url, allowedProtocols) {
  if (typeof url !== "string" || url.length === 0 || DISALLOWED_URL_CHARS_RE.test(url)) {
    return null;
  }
  const schemeMatch = /^(https?):\/\//i.exec(url);
  if (!schemeMatch) {
    return null;
  }
  const expectedProtocol = `${schemeMatch[1].toLowerCase()}:`;
  if (!allowedProtocols.includes(expectedProtocol)) {
    return null;
  }
  const afterScheme = url.slice(schemeMatch[0].length);
  const delimIndex = afterScheme.search(/[/?#]/);
  const rawAuthority = delimIndex === -1 ? afterScheme : afterScheme.slice(0, delimIndex);
  if (rawAuthority.length === 0 || rawAuthority.includes("@")) {
    return null;
  }

  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (
    parsed.protocol !== expectedProtocol ||
    parsed.hostname.length === 0 ||
    parsed.username !== "" ||
    parsed.password !== ""
  ) {
    return null;
  }
  return { parsed, rawAuthority };
}

/**
 * Return true only for absolute HTTPS URLs whose whole authority matches archiveHost,
 * with no whitespace, no userinfo, and no explicit port (including :443).
 */
export function isAllowedArchiveUrl(url, archiveHost) {
  if (
    typeof archiveHost !== "string" ||
    archiveHost.length === 0 ||
    DISALLOWED_HOST_CHARS_RE.test(archiveHost)
  ) {
    return false;
  }
  const info = parseSafeHttpUrl(url, ["https:"]);
  if (!info) {
    return false;
  }
  const { parsed, rawAuthority } = info;
  // Inspect raw authority before trusting URL normalization, which strips default :443.
  if (
    rawAuthority.includes(":") ||
    rawAuthority.includes("[") ||
    rawAuthority.includes("]") ||
    rawAuthority.includes("\\") ||
    parsed.port !== ""
  ) {
    return false;
  }
  const expected = archiveHost.toLowerCase();
  return (
    parsed.hostname.toLowerCase() === expected &&
    rawAuthority.toLowerCase() === expected
  );
}

/**
 * Return true only for absolute http: or https: URLs without whitespace or userinfo.
 */
export function validateAttributionLink(url) {
  return parseSafeHttpUrl(url, ["https:", "http:"]) !== null;
}

/**
 * Validate a comparison.json payload against the ADR 0019 public contract.
 */
export function validateComparisonPayload(data) {
  if (!isPlainObject(data)) {
    throw new Error("Invalid comparison: root must be an object");
  }
  if (!hasExactKeys(data, ROOT_KEYS)) {
    throw new Error(`Invalid comparison: root keys must be exactly ${ROOT_KEYS.join(", ")}`);
  }
  if (data.schema_version !== 1) {
    throw new Error("Invalid comparison: schema_version must be 1");
  }
  if (typeof data.producing_commit !== "string" || !COMMIT_RE.test(data.producing_commit)) {
    throw new Error("Invalid comparison: producing_commit must be a 40-character lowercase hex commit hash");
  }
  if (typeof data.manifest_sha256 !== "string" || !SHA256_RE.test(data.manifest_sha256)) {
    throw new Error("Invalid comparison: manifest_sha256 must be a 64-character lowercase hex digest");
  }
  for (const key of ["sample_id", "earlier_window", "later_window"]) {
    if (typeof data[key] !== "string") {
      throw new Error(`Invalid comparison: ${key} must be a string`);
    }
  }
  if (
    data.archive_host !== null &&
    (typeof data.archive_host !== "string" || data.archive_host.trim().length === 0)
  ) {
    throw new Error("Invalid comparison: archive_host must be a non-empty string or null");
  }

  let validatedAttribution = null;
  if (data.attribution !== null) {
    if (!isPlainObject(data.attribution) || !hasExactKeys(data.attribution, ATTRIBUTION_KEYS)) {
      throw new Error("Invalid comparison: attribution must be null or an object of the attribution strings");
    }
    validatedAttribution = {};
    for (const key of ATTRIBUTION_KEYS) {
      if (typeof data.attribution[key] !== "string") {
        throw new Error(`Invalid comparison: attribution.${key} must be a string`);
      }
      validatedAttribution[key] = data.attribution[key];
    }
  }

  if (!isPlainObject(data.summary) || !hasExactKeys(data.summary, SUMMARY_KEYS)) {
    throw new Error("Invalid comparison: summary must be an object with exact summary keys");
  }
  if (!Array.isArray(data.pages)) {
    throw new Error("Invalid comparison: pages must be an array");
  }

  const seenUrls = new Set();
  const counts = { compared: 0, comparison_incomplete: 0 };
  let pageWordsSum = 0;
  let largestPage = 0;
  const validatedPages = [];

  for (const page of data.pages) {
    if (!isPlainObject(page) || !hasExactKeys(page, PAGE_KEYS)) {
      throw new Error(`Invalid comparison: each page must be an object with ${PAGE_KEYS.join(", ")}`);
    }
    if (typeof page.url !== "string" || page.url.length === 0 || seenUrls.has(page.url)) {
      throw new Error("Invalid comparison: each page needs its own non-empty url string");
    }
    seenUrls.add(page.url);

    if (page.status !== "compared" && page.status !== "comparison_incomplete") {
      throw new Error(`Invalid comparison: page ${page.url} has unknown status`);
    }

    for (const linkKey of ["earlier_capture_url", "later_capture_url"]) {
      const linkVal = page[linkKey];
      if (linkVal !== null && typeof linkVal !== "string") {
        throw new Error(`Invalid comparison: page ${page.url} has non-string ${linkKey}`);
      }
    }

    if (page.status === "compared") {
      if (!isNonNegativeInt(page.new_words)) {
        throw new Error(`Invalid comparison: page ${page.url} must have non-negative integer new_words`);
      }
      pageWordsSum += page.new_words;
      largestPage = Math.max(largestPage, page.new_words);
    } else if (page.new_words !== null) {
      throw new Error(`Invalid comparison: incomplete page ${page.url} must have null new_words`);
    }

    counts[page.status] += 1;
    validatedPages.push({
      url: page.url,
      status: page.status,
      new_words: page.new_words,
      earlier_capture_url: page.earlier_capture_url,
      later_capture_url: page.later_capture_url,
    });
  }

  const { compared_pages: comparedPages, excluded_pages: excludedPages, distinct_new_words: distinctNewWords } =
    data.summary;
  if (!isNonNegativeInt(comparedPages) || comparedPages !== counts.compared) {
    throw new Error("Invalid comparison: summary.compared_pages does not match pages");
  }
  if (!isNonNegativeInt(excludedPages) || excludedPages !== counts.comparison_incomplete) {
    throw new Error("Invalid comparison: summary.excluded_pages does not match pages");
  }
  if (
    !isNonNegativeInt(distinctNewWords) ||
    distinctNewWords < largestPage ||
    distinctNewWords > pageWordsSum
  ) {
    throw new Error(
      "Invalid comparison: summary.distinct_new_words must lie between the largest page count and page totals",
    );
  }

  return {
    schema_version: data.schema_version,
    sample_id: data.sample_id,
    producing_commit: data.producing_commit,
    manifest_sha256: data.manifest_sha256,
    earlier_window: data.earlier_window,
    later_window: data.later_window,
    archive_host: data.archive_host,
    attribution: validatedAttribution,
    summary: {
      compared_pages: comparedPages,
      excluded_pages: excludedPages,
      distinct_new_words: distinctNewWords,
    },
    pages: validatedPages,
  };
}

/**
 * Filter pages by URL substring and status, then sort deterministically without mutating input.
 */
export function filterAndSortPages(pages, options = {}) {
  if (!Array.isArray(pages)) {
    throw new TypeError("pages must be an array");
  }
  const { query = "", statusFilter = "all", sortBy = "new_words_desc" } = options ?? {};
  if (!VALID_STATUS_FILTERS.has(statusFilter)) {
    throw new Error(`Unsupported statusFilter: ${String(statusFilter)}`);
  }
  if (!VALID_SORT_MODES.has(sortBy)) {
    throw new Error(`Unsupported sortBy: ${String(sortBy)}`);
  }

  const normalizedQuery = typeof query === "string" ? query.trim().toLowerCase() : "";
  const filtered = pages.filter((page) => {
    if (statusFilter !== "all" && page.status !== statusFilter) {
      return false;
    }
    if (normalizedQuery.length > 0 && !page.url.toLowerCase().includes(normalizedQuery)) {
      return false;
    }
    return true;
  });

  return filtered.sort((a, b) => {
    if (sortBy === "url_asc") {
      return compareText(a.url, b.url);
    }
    const aNull = a.new_words === null;
    const bNull = b.new_words === null;
    if (aNull !== bNull) {
      return aNull ? 1 : -1;
    }
    if (!aNull && !bNull && a.new_words !== b.new_words) {
      return sortBy === "new_words_asc"
        ? a.new_words - b.new_words
        : b.new_words - a.new_words;
    }
    return compareText(a.url, b.url);
  });
}

/**
 * Build GitHub reproduction links and demo command from a validated comparison document.
 */
export function buildReproduceInfo(comparison, repoBaseUrl = DEFAULT_REPO_URL) {
  if (!isPlainObject(comparison) || typeof comparison.producing_commit !== "string" || !COMMIT_RE.test(comparison.producing_commit)) {
    throw new Error("producing_commit must be a 40-character lowercase hex commit hash");
  }
  if (typeof repoBaseUrl !== "string") {
    throw new Error("repoBaseUrl must be a valid http or https URL");
  }
  const repoUrl = repoBaseUrl.replace(/\/+$/, "");
  if (!validateAttributionLink(repoUrl)) {
    throw new Error("repoBaseUrl must be a valid http or https URL");
  }
  const commit = comparison.producing_commit;
  const manifestUrl =
    typeof comparison.sample_id === "string" && SAFE_SAMPLE_ID_RE.test(comparison.sample_id)
      ? `${repoUrl}/blob/${commit}/fixtures/${comparison.sample_id}/manifest.json`
      : null;

  return {
    repoUrl,
    treeUrl: `${repoUrl}/tree/${commit}`,
    manifestUrl,
    shortCommit: commit.slice(0, 12),
    demoCommand: `git checkout ${commit} && make demo`,
  };
}
