import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Copy, Check } from 'lucide-react'
import type { ChatMessage as ChatMessageType } from '@/hooks/useAiChat'

function renderInline(text: string): ReactNode {
  const regex = /(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`(.+?)`)|(\[(.+?)\]\((.+?)\))/g
  const parts: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }

    if (match[1]) {
      parts.push(<strong key={key++}>{match[2]}</strong>)
    } else if (match[3]) {
      parts.push(<em key={key++}>{match[4]}</em>)
    } else if (match[5]) {
      parts.push(
        <code key={key++} className="bg-black/40 rounded px-1.5 py-0.5 text-xs font-mono text-emerald-400">
          {match[6]}
        </code>,
      )
    } else if (match[7]) {
      parts.push(
        <a
          key={key++}
          href={match[9]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline underline-offset-2 hover:text-primary/80"
        >
          {match[8]}
        </a>,
      )
    }

    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts.length === 0 ? text : parts
}

function renderMarkdown(text: string): ReactNode {
  if (!text) return null

  const lines = text.split('\n')
  const elements: ReactNode[] = []
  let inCodeBlock = false
  let codeContent = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (line.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <pre key={`cb-${i}`} className="bg-black/40 rounded-lg p-3 my-2 overflow-x-auto">
            <code className="text-sm font-mono text-green-400">{codeContent.trim()}</code>
          </pre>,
        )
        codeContent = ''
        inCodeBlock = false
      } else {
        inCodeBlock = true
      }
      continue
    }

    if (inCodeBlock) {
      codeContent += line + '\n'
      continue
    }

    if (line.trim() === '') {
      elements.push(<div key={`sp-${i}`} className="h-2" />)
      continue
    }

    if (line.startsWith('# ')) {
      elements.push(<h3 key={i} className="text-base font-bold mb-1">{renderInline(line.slice(2))}</h3>)
      continue
    }

    if (line.startsWith('## ')) {
      elements.push(<h4 key={i} className="text-sm font-bold mb-1">{renderInline(line.slice(3))}</h4>)
      continue
    }

    if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <li key={i} className="ml-4 list-disc text-sm leading-relaxed">{renderInline(line.slice(2))}</li>,
      )
      continue
    }

    elements.push(<p key={i} className="text-sm leading-relaxed">{renderInline(line)}</p>)
  }

  if (inCodeBlock && codeContent) {
    elements.push(
      <pre key="cb-end" className="bg-black/40 rounded-lg p-3 my-2 overflow-x-auto">
        <code className="text-sm font-mono text-green-400">{codeContent.trim()}</code>
      </pre>,
    )
  }

  return elements.length === 1 ? elements[0] : elements
}

interface ChatMessageProps {
  message: ChatMessageType
  isStreaming?: boolean
}

export default function ChatMessage({ message, isStreaming }: ChatMessageProps) {
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'

  const handleCopy = async () => {
    if (!message.content) return
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may not be available
    }
  }

  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'group relative max-w-[85%] rounded-2xl px-4 py-2.5',
          isUser
            ? 'bg-primary text-primary-foreground rounded-br-md'
            : 'bg-secondary/80 text-secondary-foreground rounded-bl-md',
        )}
      >
        <div className={cn(isStreaming && !message.content && 'min-h-[28px]')}>
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : message.content ? (
            <div className="prose-sm max-w-none text-sm [&_p]:my-1 [&_li]:my-0.5">
              {renderMarkdown(message.content)}
            </div>
          ) : isStreaming ? (
            <span className="inline-block size-2 rounded-full bg-foreground/60 animate-pulse" />
          ) : null}
        </div>

        <span
          className={cn(
            'absolute -bottom-5 text-[10px] text-muted-foreground/50 whitespace-nowrap opacity-0 transition-opacity',
            isUser ? 'right-0' : 'left-0',
            'group-hover:opacity-100',
          )}
        >
          {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>

        {!isUser && message.content && (
          <button
            onClick={handleCopy}
            className="absolute -top-2 -right-2 flex size-6 items-center justify-center rounded-full bg-card border border-border/50 opacity-0 shadow-sm transition-opacity hover:bg-secondary group-hover:opacity-100"
            title="Copy message"
          >
            {copied ? (
              <Check className="size-3 text-emerald-400" />
            ) : (
              <Copy className="size-3 text-muted-foreground" />
            )}
          </button>
        )}
      </div>
    </div>
  )
}
