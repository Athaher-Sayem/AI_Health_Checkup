/** Keep report counts in English digits, matching the server's summaries. */
export function formatNumber(value) {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? String(n) : '0'
}
