// Same-origin calls to the gateway. The session cookie travels on its own (ADR 0018);
// this code never sees or stores the Odoo key.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Listener = () => void;
const signedOutListeners = new Set<Listener>();

/** Called when the gateway answers 401: the session ended or the key was revoked. */
export function onSignedOut(listener: Listener): () => void {
  signedOutListeners.add(listener);
  return () => signedOutListeners.delete(listener);
}

async function failure(response: Response): Promise<ApiError> {
  let code = "http_" + response.status;
  let message = response.statusText || "Request failed";
  try {
    const body = (await response.json()) as { error?: string; message?: string; detail?: unknown };
    if (body.error) code = body.error;
    if (body.message) message = body.message;
    else if (response.status === 422) code = "invalid_request";
  } catch {
    // not JSON: keep the status text
  }
  if (response.status === 401) signedOutListeners.forEach((listener) => listener());
  return new ApiError(response.status, code, message);
}

export async function request(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "The gateway could not be reached.");
  }
  if (!response.ok) throw await failure(response);
  return response;
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await request(method, path, body);
  return (await response.json()) as T;
}

export const get = <T>(path: string) => api<T>("GET", path);
export const post = <T>(path: string, body: unknown = {}) => api<T>("POST", path, body);
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const del = <T>(path: string) => api<T>("DELETE", path);
