const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

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
  const normalizedPath = path.replace(/^\/+/, '')
  const response = await fetch(`${baseUrl}/${normalizedPath}`, {
    ...init,
    headers,
  })
  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const problem = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : {}
    const message = typeof problem.message === 'string' ? problem.message
      : typeof problem.detail === 'string' ? problem.detail
        : typeof payload === 'string' && payload ? payload : `Request failed (${response.status})`
    const code = typeof problem.code === 'string' ? problem.code : undefined
    throw new ApiError(message, response.status, code)
  }
  return payload as T
}
