import { useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { MessageCircle, X } from 'lucide-react'
import AiChatPanel from './AiChatPanel'

interface AiChatWidgetProps {
  pageContext?: string
  userRole?: string
}

export default function AiChatWidget({ pageContext }: AiChatWidgetProps) {
  const [isOpen, setIsOpen] = useState(false)

  const toggle = useCallback(() => setIsOpen(prev => !prev), [])
  const close = useCallback(() => setIsOpen(false), [])

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
      {/* Chat Panel */}
      <div
        className={cn(
          'origin-bottom-right transition-all duration-300 ease-out',
          isOpen
            ? 'opacity-100 scale-100 translate-y-0'
            : 'opacity-0 scale-95 translate-y-4 pointer-events-none',
        )}
      >
        <div className="w-[380px] max-w-[calc(100vw-3rem)] h-[560px] max-h-[calc(100vh-8rem)] rounded-2xl border border-border/60 bg-card shadow-2xl shadow-black/40 overflow-hidden flex flex-col">
          <AiChatPanel pageContext={pageContext} onClose={close} />
        </div>
      </div>

      {/* Toggle Button */}
      <button
        onClick={toggle}
        className={cn(
          'relative flex size-12 items-center justify-center rounded-full shadow-lg shadow-black/30 transition-all duration-300 hover:scale-105 active:scale-95',
          isOpen
            ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
            : 'bg-primary text-primary-foreground hover:bg-primary/90',
        )}
        title={isOpen ? 'Close chat' : 'Open chat'}
      >
        {isOpen ? (
          <X className="size-5" />
        ) : (
          <MessageCircle className="size-5" />
        )}
      </button>
    </div>
  )
}
