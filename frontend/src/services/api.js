const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function parse(response) {
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload?.detail ??
      payload?.message ??
      'অনুরোধটি সম্পন্ন হয়নি। আবার চেষ্টা করুন।'
    const message =
      typeof detail === 'string' ? detail : 'অনুরোধটি সম্পন্ন হয়নি। আবার চেষ্টা করুন।'
    const error = new Error(message)
    error.status = response.status
    error.payload = payload
    throw error
  }

  return payload
}

export function getHealth() {
  return fetch(`${API_BASE}/api/health`).then(parse)
}

export function uploadReport(file) {
  const form = new FormData()
  form.append('file', file)

  return fetch(`${API_BASE}/api/reports/upload`, {
    method: 'POST',
    body: form,
  }).then(parse)
}

export function analyzeReport(reportId) {
  return fetch(`${API_BASE}/api/reports/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ report_id: reportId }),
  }).then(parse)
}

export function getReport(reportId) {
  return fetch(`${API_BASE}/api/reports/${reportId}`).then(parse)
}

export function deleteReport(reportId) {
  return fetch(`${API_BASE}/api/reports/${reportId}`, {
    method: 'DELETE',
  }).then(parse)
}
