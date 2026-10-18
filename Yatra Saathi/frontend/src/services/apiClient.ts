const rawBaseUrl = import.meta.env.VITE_API_BASE_URL
const baseUrl = (rawBaseUrl !== undefined ? rawBaseUrl : 'http://localhost:8000').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (!headers.has('Authorization')) {
    try {
      const token = typeof localStorage !== 'undefined' ? localStorage.getItem('yatra-auth-token') : null
      if (token) headers.set('Authorization', `Bearer ${token}`)
    } catch {
      // ignore
    }
  }
  const normalizedPath = path.replace(/^\/+/, '')
  let response: Response
  try {
    response = await fetch(`${baseUrl}/${normalizedPath}`, {
      ...init,
      headers,
    })
  } catch (cause: any) {
    const msg = cause?.message || 'Network error'
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || cause?.name === 'TypeError') {
      throw new ApiError(`Cannot connect to backend server at ${baseUrl || 'local API'}. Please ensure the Yatra Saathi backend is running on port 8000.`, 0, 'CONNECTION_REFUSED')
    }
    throw cause
  }
  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const problem = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : {}
    // Backend envelope: { ok: false, refusal: { code, message } }. FastAPI validation: { detail: [...] }.
    const refusal = typeof problem.refusal === 'object' && problem.refusal !== null ? problem.refusal as Record<string, unknown> : {}
    // FastAPI validation errors carry the reason in detail[0].msg ("Value error, …").
    const firstDetail = Array.isArray(problem.detail) && typeof problem.detail[0]?.msg === 'string'
      ? String(problem.detail[0].msg).replace(/^Value error, /, '') : undefined
    const message = typeof refusal.message === 'string' ? refusal.message
      : typeof problem.message === 'string' ? problem.message
        : typeof problem.detail === 'string' ? problem.detail
          : firstDetail ? firstDetail
          : typeof payload === 'string' && payload ? payload : `Request failed (${response.status})`
    const code = typeof refusal.code === 'string' ? refusal.code
      : typeof problem.code === 'string' ? problem.code
        : Array.isArray(problem.detail) ? 'VALIDATION_ERROR' : undefined
    throw new ApiError(message, response.status, code)
  }
  return payload as T
}

/** Unwraps the backend's `{ ok, data }` success envelope. */
export async function apiData<T>(path: string, init?: RequestInit): Promise<T> {
  const envelope = await apiRequest<{ ok: boolean; data: T }>(path, init)
  return envelope.data
}
