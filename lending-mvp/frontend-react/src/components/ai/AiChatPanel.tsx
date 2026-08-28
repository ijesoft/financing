import { useState, useRef, useEffect, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { Send, Square, Bot, Sparkles } from 'lucide-react'
import { useAiChat } from '@/hooks/useAiChat'
import ChatMessage from './ChatMessage'
import TypingIndicator from './TypingIndicator'

interface AiChatPanelProps {
  pageContext?: string
  onClose: () => void
}

const SUGGESTED_PROMPTS = [
  'How do I create a new loan?',
  'How do I generate financial reports?',
  'What can I do in the Customer Portal?',
  'How do collections work?',
]

export default function AiChatPanel({ pageContext, onClose }: AiChatPanelProps) {
  const {
    messages,
    isLoading,
    error,
    sendMessage,
    cancelStream,
    clearChat,
    retryLast,
  } = useAiChat(pageContext ?? null)

  const [input, setInput] = useState('')
  const [isAtBottom, setIsAtBottom] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const scrollToBottom = useCallback((force = false) => {
    if (force || isAtBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [isAtBottom])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleScroll = useCallback(() => {
    const container = messagesContainerRef.current
    if (!container) return
    const threshold = 50
    const atBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < threshold
    setIsAtBottom(atBottom)
  }, [])

  const handleSend = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isLoading) return
    setInput('')
    sendMessage(trimmed)
    setIsAtBottom(true)
  }, [input, isLoading, sendMessage])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    if (e.target.style) {
      e.target.style.height = 'auto'
      e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`
    }
  }, [])

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15">
            <Bot className="size-4 text-primary" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">AI Assistant</h3>
            <p className="text-[10px] text-muted-foreground/60">Ask me anything</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-secondary transition-colors"
              title="Clear chat"
            >
              <Sparkles className="size-3.5" />
            </button>
          )}
          <button
            onClick={onClose}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-secondary transition-colors"
            title="Close"
          >
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg" className="size-3.5">
              <path d="M11.7816 4.03157C12.0062 3.80702 12.0062 3.44295 11.7816 3.2184C11.5571 2.99385 11.193 2.99385 10.9685 3.2184L7.50005 6.68682L4.03164 3.2184C3.80708 2.99385 3.44301 2.99385 3.21846 3.2184C2.99391 3.44295 2.99391 3.80702 3.21846 4.03157L6.68688 7.5L3.21846 10.9684C2.99391 11.193 2.99391 11.5571 3.21846 11.7816C3.44301 12.0062 3.80708 12.0062 4.03164 11.7816L7.50005 8.31318L10.9685 11.7816C11.193 12.0062 11.5571 12.0062 11.7816 11.7816C12.0062 11.5571 12.0062 11.193 11.7816 10.9684L8.31322 7.5L11.7816 4.03157Z" fill="currentColor" fillRule="evenodd" clipRule="evenodd" />
            </svg>
          </button>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={messagesContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-4 scrollbar-thin"
      >
        {messages.length === 0 && !error ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-8">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 mb-4">
              <Bot className="size-6 text-primary" />
            </div>
            <h4 className="text-sm font-medium text-foreground mb-2">Hi! I'm your AI assistant</h4>
            <p className="text-xs text-muted-foreground/70 max-w-[260px] mb-6">
              Ask me anything about how to use this system!
            </p>
            <div className="space-y-2 w-full max-w-[280px]">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => {
                    sendMessage(prompt)
                    setIsAtBottom(true)
                  }}
                  className="w-full text-left px-3.5 py-2.5 rounded-lg border border-border/40 bg-secondary/30 hover:bg-secondary/60 hover:border-border/70 transition-all duration-200 text-xs text-muted-foreground hover:text-foreground"
                  disabled={isLoading}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                isStreaming={isLoading && msg.role === 'assistant' && msg.content === ''}
              />
            ))}

            {isLoading && messages[messages.length - 1]?.content && (
              <div className="flex justify-start">
                <div className="bg-secondary/80 rounded-2xl rounded-bl-md px-4 py-2.5">
                  <TypingIndicator />
                </div>
              </div>
            )}

            {error && (
              <div className="flex justify-center">
                <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/10 border border-destructive/20">
                  <span className="text-xs text-destructive">{error}</span>
                  <button
                    onClick={retryLast}
                    className="text-xs text-primary hover:text-primary/80 underline underline-offset-2"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border/50 px-4 py-3">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              rows={1}
              disabled={isLoading}
              className={cn(
                'w-full resize-none rounded-xl border border-input bg-background px-3.5 py-2.5 pr-10 text-sm placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50',
                'scrollbar-thin min-h-[38px] max-h-[120px]',
              )}
            />
            <span className="absolute right-3 bottom-2.5 text-[10px] text-muted-foreground/30 pointer-events-none select-none">
              {input.length}/2000
            </span>
          </div>
          {isLoading ? (
            <button
              onClick={cancelStream}
              className="flex size-[38px] shrink-0 items-center justify-center rounded-xl bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
              title="Stop generating"
            >
              <Square className="size-4 fill-current" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex size-[38px] shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Send message"
            >
              <Send className="size-4" />
            </button>
          )}
        </div>
        <div className="mt-2 flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground/40">
            Responses are AI-generated. Verify important information.
          </p>
        </div>
      </div>
    </div>
  )
}
