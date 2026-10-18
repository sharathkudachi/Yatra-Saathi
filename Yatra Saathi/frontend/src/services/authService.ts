import { ApiError, apiData } from './apiClient'

// Sign-in always talks to the backend (even when VITE_USE_MOCK_API is on): users live
// in the database, so there is no meaningful mock for them.
export type AuthUser = {
  userId: string
  username?: string
  displayName: string
  email: string
  homeCurrency: string
  locale: string
}

export type LoginCredentials = {
  identifier?: string
  password?: string
  userId?: string
  displayName?: string
  email?: string
}

export type RegisterDetails = {
  fullName: string
  username: string
  email: string
  password: string
}

type ApiUser = {
  user_id: string
  username?: string
  display_name: string
  email: string
  home_currency: string
  locale: string
}

const TOKEN_KEY = 'yatra-auth-token'

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

function writeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* storage unavailable: the session lasts until reload */ }
}

function toUser(user: ApiUser): AuthUser {
  return {
    userId: user.user_id,
    username: user.username,
    displayName: user.display_name,
    email: user.email,
    homeCurrency: user.home_currency,
    locale: user.locale,
  }
}

export const authService = {
  /**
   * Authenticate with either username/email + password, or legacy credentials.
   * Passwords are submitted via HTTPS request body and NEVER logged or cached.
   */
  async login(credentials: LoginCredentials): Promise<AuthUser> {
    const payload = credentials.password !== undefined
      ? { identifier: (credentials.identifier || '').trim(), password: credentials.password }
      : {
          user_id: (credentials.userId || '').trim(),
          display_name: (credentials.displayName || '').trim(),
          email: (credentials.email || '').trim(),
        }

    const data = await apiData<{ token: string; user: ApiUser }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    writeToken(data.token)
    return toUser(data.user)
  },

  /**
   * Register a new user account with secure Argon2id password hashing on the backend.
   */
  async register({ fullName, username, email, password }: RegisterDetails): Promise<AuthUser> {
    const data = await apiData<{ token: string; user: ApiUser }>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        full_name: fullName.trim(),
        username: username.trim().toLowerCase(),
        email: email.trim().toLowerCase(),
        password,
      }),
    })
    writeToken(data.token)
    return toUser(data.user)
  },

  /** Restores the signed-in user from a stored token; clears it if the backend rejects it. */
  async restore(): Promise<AuthUser | null> {
    const token = readToken()
    if (!token) return null
    try {
      const data = await apiData<{ user: ApiUser }>('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      return toUser(data.user)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) writeToken(null)
      return null
    }
  },

  logout() { writeToken(null) },

  authHeaders(): Record<string, string> {
    const token = readToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  },
}

/** Maps an auth failure to a user-friendly descriptive message. */
export function authErrorMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === 'LOGIN_MISMATCH') return 'Invalid username/email or password.'
    if (cause.code === 'USER_INACTIVE') return 'Account is inactive. Please contact support.'
    if (cause.code === 'AUTH_RATE_LIMITED') return cause.message || 'Too many attempts. Access temporarily locked.'
    if (cause.code === 'DUPLICATE_USERNAME') return 'This username is already taken. Please choose another.'
    if (cause.code === 'DUPLICATE_EMAIL') return 'An account with this email already exists.'
    if (cause.code === 'WEAK_PASSWORD') return cause.message || 'Password must be at least 8 characters long.'
    if (cause.code === 'INVALID_USERNAME') return cause.message || 'Username must be 3-30 characters (letters, numbers, underscore).'
    if (cause.code === 'INVALID_EMAIL') return 'Please enter a valid email address.'
    if (cause.code === 'INVALID_NAME') return 'Please enter a valid full name.'
    if (cause.code === 'VALIDATION_ERROR') return cause.message || 'Please check the required fields.'
    return cause.message || 'Authentication failed.'
  }
  return cause instanceof Error ? cause.message : 'Network error: could not connect to authentication service.'
}

/** Maps a login failure to a translation key. */
export function loginErrorKey(cause: unknown) {
  if (cause instanceof ApiError) {
    if (cause.code === 'LOGIN_MISMATCH') return 'auth.mismatch'
    if (cause.code === 'USER_INACTIVE') return 'auth.inactive'
    if (cause.code === 'VALIDATION_ERROR') return 'auth.incomplete'
    return 'auth.failed'
  }
  return 'auth.unreachable'
}
