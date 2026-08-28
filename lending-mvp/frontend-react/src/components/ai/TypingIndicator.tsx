import { cn } from '@/lib/utils'

interface TypingIndicatorProps {
  className?: string
}

export default function TypingIndicator({ className }: TypingIndicatorProps) {
  return (
    <div className={cn('flex items-center gap-1.5 px-1 py-2', className)}>
      <span className="typing-dot size-1.5 rounded-full bg-muted-foreground/60 animate-bounce-dot" style={{ animationDelay: '0ms' }} />
      <span className="typing-dot size-1.5 rounded-full bg-muted-foreground/60 animate-bounce-dot" style={{ animationDelay: '150ms' }} />
      <span className="typing-dot size-1.5 rounded-full bg-muted-foreground/60 animate-bounce-dot" style={{ animationDelay: '300ms' }} />
    </div>
  )
}
