export class CurrencyAmount {
  private amount: number

  constructor(amount: number | string) {
    this.amount = typeof amount === 'string' ? parseFloat(amount) : amount
  }

  format(currency = 'PHP'): string {
    return new Intl.NumberFormat('en-PH', {
      style: 'currency',
      currency,
    }).format(this.amount)
  }

  value(): number {
    return this.amount
  }
}
