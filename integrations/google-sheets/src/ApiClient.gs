/**
 * OpenVA for Google Sheets — HTTP adapter over the OpenVA /v1 API.
 *
 * This file is the only place that calls UrlFetchApp. It never logs request payloads or
 * vendor identities, and it never attaches an API key or bearer token. The client is
 * designed for an OpenVA deployment running with OPENVA_PUBLIC_READ_ENABLED=true.
 *
 * Only two endpoints are ever called:
 *   GET  {base}/v1/catalog/meta   (connection test)
 *   POST {base}/v1/enrich         (enrichment)
 */

/** Read and validate the configured base URL from document properties. */
function getConfiguredBaseUrl() {
  var raw = PropertiesService.getDocumentProperties().getProperty(OPENVA_API_BASE_URL_KEY);
  return normalizeBaseUrl(raw);
}

/**
 * Map a non-2xx HTTP status to a user-facing, non-leaking message. Raw HTML error pages
 * and request payloads are never surfaced.
 */
function describeHttpError(status) {
  if (status === 401) {
    return (
      'This OpenVA endpoint does not permit public read access. Ask the service ' +
      'administrator to enable the read-only public API or provide an approved intermediary.'
    );
  }
  if (status === 404) {
    return 'The configured endpoint did not expose the OpenVA API (404). Check the base URL.';
  }
  if (status === 413) {
    return 'The request was too large for the service (413). Reduce the number of rows and retry.';
  }
  if (status === 422) {
    return 'The service rejected the request as invalid (422). Check the input columns.';
  }
  return 'The OpenVA service returned an error (HTTP ' + status + ').';
}

/**
 * Perform a JSON request with bounded exponential-backoff retries for transient statuses
 * only. Never retries 400/401/404/413/422. Returns a structured result; callers validate
 * the response contract before trusting it.
 *
 * @returns {{ok: true, status: number, body: Object} | {ok: false, error: string}}
 */
function fetchJson(url, options) {
  var attempt = 0;
  while (true) {
    var response;
    try {
      response = UrlFetchApp.fetch(url, options);
    } catch (e) {
      // Network/transport failure (DNS, TLS, timeout). Retry within bounds, then give up.
      if (attempt < OPENVA_MAX_RETRIES) {
        Utilities.sleep(backoffMs(attempt));
        attempt += 1;
        continue;
      }
      return { ok: false, error: 'Could not reach the OpenVA service. Check the endpoint and your connection.' };
    }
    var status = response.getResponseCode();
    if (status >= 200 && status < 300) {
      var text = response.getContentText();
      var parsed;
      try {
        parsed = JSON.parse(text);
      } catch (parseError) {
        return { ok: false, error: 'The OpenVA service returned a non-JSON response.' };
      }
      return { ok: true, status: status, body: parsed };
    }
    if (isRetryableStatus(status) && attempt < OPENVA_MAX_RETRIES) {
      Utilities.sleep(backoffMs(attempt));
      attempt += 1;
      continue;
    }
    return { ok: false, error: describeHttpError(status) };
  }
}

/** Small exponential backoff: 500ms, 1000ms, ... bounded by the retry cap. */
function backoffMs(attempt) {
  return 500 * Math.pow(2, attempt);
}

/**
 * GET /v1/catalog/meta. Validates the snapshot/guarantees/not_advice contract.
 *
 * @returns {{ok: true, snapshot: Object, guarantees: Object} | {ok: false, error: string}}
 */
function testApiConnection(baseUrl) {
  var result = fetchJson(joinUrl(baseUrl, OPENVA_CATALOG_META_PATH), {
    method: 'get',
    muteHttpExceptions: true,
  });
  if (!result.ok) {
    return result;
  }
  var body = result.body;
  var snapshot = body && body.snapshot;
  if (!snapshot || !snapshot.snapshot_digest) {
    return { ok: false, error: 'The endpoint did not return a valid OpenVA catalogue snapshot.' };
  }
  if (!body.guarantees || body.not_advice !== true) {
    return { ok: false, error: 'The endpoint did not return the expected OpenVA metadata contract.' };
  }
  return { ok: true, snapshot: snapshot, guarantees: body.guarantees };
}

/**
 * POST /v1/enrich for one batch of vendor payloads.
 *
 * @param {string} baseUrl normalized base URL
 * @param {Array<Object>} vendors batch of vendor identity payloads (already bounded)
 * @returns {{ok: true, snapshotDigest: string, results: Array} | {ok: false, error: string}}
 */
function enrichBatch(baseUrl, vendors) {
  var result = fetchJson(joinUrl(baseUrl, OPENVA_ENRICH_PATH), {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ vendors: vendors }),
    muteHttpExceptions: true,
  });
  if (!result.ok) {
    return result;
  }
  var expectedRowIds = vendors.map(function (vendor) {
    return vendor.row_id;
  });
  return validateEnrichmentResponse(result.body, expectedRowIds);
}
