import { API_URL } from '@/lib/config'

const getHeaders = () => {
  const token = localStorage.getItem('access_token')
  return {
    'Content-Type': 'application/json',
    'Authorization': token ? `Bearer ${token}` : '',
  }
}

export interface Session {
  session_id: string
  message_count: number
  created_at: string
}

export interface ModelInfo {
  provider: string
  model: string
}

export interface StreamCallbacks {
  onToken: (token: string) => void
  onDone: (sessionId: string) => void
  onError: (message: string) => void
}

export async function fetchModels(): Promise<ModelInfo> {
  const response = await fetch(`${API_URL}/api/chat/models`, {
    headers: getHeaders(),
  })
  if (!response.ok) {
    throw new Error('Failed to fetch model info')
  }
  return response.json()
}

export async function fetchSessions(): Promise<Session[]> {
  const response = await fetch(`${API_URL}/api/chat/sessions`, {
    headers: getHeaders(),
  })
  if (!response.ok) {
    throw new Error('Failed to fetch sessions')
  }
  const data = await response.json()
  return data.sessions
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API_URL}/api/chat/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: getHeaders(),
  })
  if (!response.ok) {
    throw new Error('Failed to delete session')
  }
}

export async function streamChat(
  message: string,
  sessionId: string | null,
  pageContext: string | null,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<string | null> {
  const response = await fetch(`${API_URL}/api/chat/stream`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      page_context: pageContext,
    }),
    signal,
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ message: 'Stream request failed' }))
    throw new Error(errorBody.message || `HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('Response body is not readable')
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let resolvedSessionId: string | null = null

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.trim()) continue

        const lines = part.split('\n')
        let eventType = ''
        let dataStr = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            dataStr = line.slice(6).trim()
          }
        }

        if (!dataStr) continue

        try {
          const data = JSON.parse(dataStr)

          switch (eventType) {
            case 'token':
              if (data.token) {
                callbacks.onToken(data.token)
              }
              break
            case 'done':
              if (data.session_id) {
                resolvedSessionId = data.session_id
                callbacks.onDone(data.session_id)
              }
              break
            case 'error':
              callbacks.onError(data.message || 'Unknown error')
              break
          }
        } catch {
          // Skip malformed JSON
        }
      }
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return resolvedSessionId
    }
    throw error
  } finally {
    reader.releaseLock()
  }

  return resolvedSessionId
}
