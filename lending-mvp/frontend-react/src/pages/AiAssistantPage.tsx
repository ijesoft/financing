import { useState, useRef, useEffect } from 'react'
import { Bot, Send, Loader2, User, Sparkles, AlertCircle } from 'lucide-react'
import { API_URL } from '@/lib/config'

interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
}

const SUGGESTED_QUESTIONS = [
    "What's the best collection strategy for a 60-day overdue loan?",
    "Explain the difference between flat rate and diminishing balance amortization",
    "What are the BSP regulations on loan collection practices?",
    "How should I handle a borrower who keeps missing payments?",
    "What is the standard loan restructuring process?",
    "What KYC documents are required for individual borrowers?",
]

export default function AiAssistantPage() {
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

    const ask = async (question: string) => {
        if (!question.trim() || loading) return
        setError('')
        setInput('')
        setMessages(prev => [...prev, { role: 'user', content: question }])
        setLoading(true)

        try {
            const token = localStorage.getItem('access_token')
            const response = await fetch(`${API_URL}/api/ai/ask`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ question: question.trim() }),
            })
            if (!response.ok) {
                const errBody = await response.json().catch(() => ({}))
                setError(errBody.detail || `Request failed (HTTP ${response.status})`)
                return
            }
            const data = await response.json()
            if (!data.success) {
                setError(data.message || 'Request failed')
                return
            }
            setMessages(prev => [...prev, { role: 'assistant', content: data.answer }])
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Failed to reach AI service')
        } finally {
            setLoading(false)
        }
    }

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        ask(input)
    }

    return (
        <div className="flex flex-col h-[calc(100vh-6rem)]">
            {/* Header */}
            <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center shadow-lg shadow-purple-500/20">
                    <Bot className="w-5 h-5 text-white" />
                </div>
                <div>
                    <h1 className="text-xl font-bold text-foreground">AI Assistant</h1>
                    <p className="text-sm text-muted-foreground">Lending & Collections Agent</p>
                </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-2">
                {messages.length === 0 && !loading && (
                    <div className="flex flex-col items-center justify-center h-full text-center px-4">
                        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center mb-4">
                            <Sparkles className="w-8 h-8 text-purple-400" />
                        </div>
                        <h2 className="text-lg font-semibold text-foreground mb-2">How can I help you today?</h2>
                        <p className="text-sm text-muted-foreground mb-6 max-w-md">
                            Ask me anything about loan products, collections strategies, regulations, or customer management.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-2xl">
                            {SUGGESTED_QUESTIONS.map((q) => (
                                <button
                                    key={q}
                                    onClick={() => ask(q)}
                                    className="text-left px-4 py-3 rounded-xl bg-secondary/50 border border-border/50 hover:bg-secondary hover:border-border text-sm text-muted-foreground hover:text-foreground transition-all duration-200"
                                >
                                    {q}
                                </button>
                            ))}
                        </div>
                    </div>
                )}

                {messages.map((msg, i) => (
                    <div
                        key={i}
                        className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                        {msg.role === 'assistant' && (
                            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center flex-shrink-0 mt-1">
                                <Bot className="w-4 h-4 text-white" />
                            </div>
                        )}
                        <div
                            className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                                msg.role === 'user'
                                    ? 'bg-gradient-to-br from-primary to-purple-600 text-white rounded-br-md shadow-lg shadow-primary/20'
                                    : 'glass border border-border/50 rounded-bl-md'
                            }`}
                        >
                            <div className="whitespace-pre-wrap">{msg.content}</div>
                        </div>
                        {msg.role === 'user' && (
                            <div className="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center flex-shrink-0 mt-1">
                                <User className="w-4 h-4 text-muted-foreground" />
                            </div>
                        )}
                    </div>
                ))}

                {loading && (
                    <div className="flex gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center flex-shrink-0 mt-1">
                            <Bot className="w-4 h-4 text-white" />
                        </div>
                        <div className="glass border border-border/50 rounded-2xl rounded-bl-md px-4 py-3">
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Thinking...
                            </div>
                        </div>
                    </div>
                )}

                {error && (
                    <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-destructive/10 border border-destructive/20 text-sm text-destructive">
                        <AlertCircle className="w-4 h-4 flex-shrink-0" />
                        {error}
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask a question about lending, collections, or regulations..."
                    disabled={loading}
                    maxLength={2000}
                    className="flex-1 px-4 py-3 bg-secondary/50 border border-border rounded-xl text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all duration-200 disabled:opacity-50"
                />
                <button
                    type="submit"
                    disabled={loading || !input.trim()}
                    className="px-4 py-3 rounded-xl bg-gradient-to-br from-primary to-purple-600 text-white font-medium shadow-lg shadow-primary/20 hover:opacity-90 active:opacity-80 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
            </form>
        </div>
    )
}
