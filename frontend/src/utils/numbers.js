const BENGALI_DIGITS = ['০', '১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯']

/**
 * Render a number using Bangla numerals, matching the numbers the backend
 * already uses inside the summary bullets.
 */
export function toBanglaNumber(value) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return '০'
  return String(n).replace(/\d/g, (d) => BENGALI_DIGITS[Number(d)])
}
