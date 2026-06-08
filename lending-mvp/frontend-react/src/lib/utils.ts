import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}

export function formatCurrency(amount: number | string | null | undefined, currency = 'PHP'): string {
    const val = Number(amount ?? 0)
    if (Number.isNaN(val)) return '₱0.00'
    return new Intl.NumberFormat('en-PH', {
        style: 'currency',
        currency,
        minimumFractionDigits: 2,
    }).format(val)
}

export function formatDate(dateStr: string | null | undefined): string {
    if (!dateStr) return '—'
    return new Date(dateStr).toLocaleDateString('en-PH', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    })
}

export function formatDateTime(dateStr: string | null | undefined): string {
    if (!dateStr) return '—'
    return new Date(dateStr).toLocaleString('en-PH', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    })
}

export function truncate(str: string, maxLength: number): string {
    if (str.length <= maxLength) return str
    return str.slice(0, maxLength) + '...'
}

export function getInitials(name: string): string {
    return name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
}

export function getLoanStatusColor(status: string): string {
    const s = status?.toLowerCase()
    if (s === 'active') return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20'
    if (s === 'paid' || s === 'closed') return 'text-blue-400 bg-blue-400/10 border-blue-400/20'
    if (s === 'overdue' || s === 'defaulted') return 'text-red-400 bg-red-400/10 border-red-400/20'
    if (s === 'pending' || s === 'under_review') return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20'
    return 'text-muted-foreground bg-muted/10 border-border'
}
