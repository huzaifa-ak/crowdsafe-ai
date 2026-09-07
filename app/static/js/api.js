/**
 * Talking to the API.
 *
 * Every failure arrives in the same shape, so it is worth unpacking once here
 * rather than at each call site:
 *
 *   { "error": { "code": "VALIDATION", "message": "...", "details": [...] } }
 */

export class ApiError extends Error {
  constructor(message, { code = 'ERROR', details = [], status = 0 } = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.details = details;
    this.status = status;
  }

  /** Problems for one field, as plain strings. */
  forField(field) {
    return this.details.filter((d) => d.field === field).map((d) => d.message);
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (cause) {
    /* fetch only rejects when the request never completed — offline, DNS,
     * connection dropped. Worth naming, because "failed to fetch" tells the
     * person nothing about what to do next. */
    throw new ApiError('Could not reach the server. Check your connection and try again.', {
      code: 'NETWORK',
    });
  }

  if (response.status === 204) return null;

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = payload && payload.error ? payload.error : {};
    throw new ApiError(error.message || `Request failed (${response.status}).`, {
      code: error.code,
      details: error.details,
      status: response.status,
    });
  }

  return payload;
}

export const api = {
  listVenues: () => request('GET', '/api/venues'),
  getVenue: (id) => request('GET', `/api/venues/${id}`),
  createVenue: (venue) => request('POST', '/api/venues', venue),
  updateVenue: (id, venue) => request('PUT', `/api/venues/${id}`, venue),
  deleteVenue: (id) => request('DELETE', `/api/venues/${id}`),
};
