// Talking to the backend.
//
// Every page uses these four functions; none of them calls fetch() directly.
// That keeps one place for the rules: JSON in and out, empty filters left out
// of the address, and every failure turned into an ApiError with a message that
// is safe to show.

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;       // HTTP status, or 0 when the server could not be reached
    this.body = body || {};     // the full JSON answer, e.g. { detail, dependencies }
  }

  /**
   * For a rejected form (status 422): which field is wrong and why.
   *   { height_cm: "Input should be greater than or equal to 120", "": "enter both scores, or ..." }
   * The "" key holds problems that concern the form as a whole.
   */
  get fieldErrors() {
    const errors = {};
    if (!Array.isArray(this.body.detail)) return errors;
    for (const item of this.body.detail) {
      const path = (item.loc || []).filter((part) => part !== 'body' && part !== 'query');
      const field = path.length ? String(path[0]) : '';
      if (!(field in errors)) errors[field] = cleanMessage(item.msg);
    }
    return errors;
  }
}

function cleanMessage(message) {
  // Pydantic prefixes our own validation messages with "Value error, ".
  const text = String(message || '').replace(/^Value error, /, '');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function describe(body) {
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const path = (item.loc || []).filter((part) => part !== 'body' && part !== 'query');
      const where = path.join(' › ').replaceAll('_', ' ');
      return where ? `${where}: ${cleanMessage(item.msg)}` : cleanMessage(item.msg);
    }).join('. ');
  }
  return 'The request failed.';
}

async function request(method, path, { params, body, text } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [name, value] of Object.entries(params || {})) {
    if (value === null || value === undefined || value === '') continue;  // an empty filter is no filter
    url.searchParams.set(name, value);
  }

  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  } else if (text !== undefined) {
    options.headers['Content-Type'] = 'text/csv';
    options.body = text;
  }

  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check that it is still running in the terminal.');
  }
  if (response.status === 204) return null;  // "done, nothing to send back"

  let data = null;
  try {
    data = await response.json();
  } catch {
    // Not JSON (should not happen for /api/ addresses); handled just below.
  }
  if (!response.ok) throw new ApiError(response.status, describe(data), data);
  return data;
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body, params) => request('POST', path, { body, params }),
  put: (path, body, params) => request('PUT', path, { body, params }),
  delete: (path, params) => request('DELETE', path, { params }),
  postText: (path, text, params) => request('POST', path, { text, params }),
};

let vocabularyRequest = null;

/** The suggestion lists and fixed choices (positions, categories, ...). Fetched once per page. */
export function vocabulary() {
  if (!vocabularyRequest) vocabularyRequest = api.get('/api/meta/vocabulary');
  return vocabularyRequest;
}
