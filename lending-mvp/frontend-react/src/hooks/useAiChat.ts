import { useState, useRef, useCallback } from 'react'
import { streamChat, deleteSession, type StreamCallbacks } from '@/api/chat'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

export function useAiChat(pageContext: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  const isLoadingRef = useRef(false)
  const sessionIdRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const accumulatorRef = useRef('')
  const assistantIdRef = useRef('')

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoadingRef.current) return

    setError(null)

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])

    isLoadingRef.current = true
    setIsLoading(true)

    const assistantId = generateId()
    assistantIdRef.current = assistantId
    accumulatorRef.current = ''

    setMessages(prev => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    }])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const callbacks: StreamCallbacks = {
        onToken: (token: string) => {
          accumulatorRef.current += token
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId
                ? { ...m, content: accumulatorRef.current }
                : m,
            ),
          )
        },
        onDone: (sid: string) => {
          sessionIdRef.current = sid
          setSessionId(sid)
        },
        onError: (msg: string) => {
          setError(msg)
          setMessages(prev => prev.filter(m => m.id !== assistantId))
        },
      }

      const newSessionId = await streamChat(
        text.trim(),
        sessionIdRef.current,
        pageContext,
        callbacks,
        controller.signal,
      )

      if (newSessionId) {
        sessionIdRef.current = newSessionId
        setSessionId(newSessionId)
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        setError(err.message || 'An error occurred')
        setMessages(prev => prev.filter(m => m.id !== assistantId))
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
        isLoadingRef.current = false
        setIsLoading(false)
      }
    }
  }, [pageContext])

  const cancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      isLoadingRef.current = false
      setIsLoading(false)
      setMessages(prev => prev.filter(m => m.id !== assistantIdRef.current))
    }
  }, [])

  const clearChat = useCallback(async () => {
    cancelStream()
    if (sessionIdRef.current) {
      try {
        await deleteSession(sessionIdRef.current)
      } catch {
        // Silently fail
      }
    }
    sessionIdRef.current = null
    setMessages([])
    setSessionId(null)
    setError(null)
  }, [cancelStream])

  const retryLast = useCallback(async () => {
    if (messages.length < 2) return

    let lastUserContent = ''
    let lastUserIndex = -1

    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        lastUserContent = messages[i].content
        lastUserIndex = i
        break
      }
    }

    if (!lastUserContent || lastUserIndex === -1) return

    setMessages(prev => prev.slice(0, lastUserIndex + 1))
    await new Promise(resolve => setTimeout(resolve, 0))
    await sendMessage(lastUserContent)
  }, [messages, sendMessage])

  return {
    messages,
    isLoading,
    error,
    sessionId,
    sendMessage,
    cancelStream,
    clearChat,
    retryLast,
  }
}
