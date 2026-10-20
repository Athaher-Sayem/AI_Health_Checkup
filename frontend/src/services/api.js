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
      'The request could not be completed. Please try again.'
    const message =
      typeof detail === 'string' ? detail : 'The request could not be completed. Please try again.'
    const error = new Error(message)
    error.status = response.status
    error.payload = payload
    throw error
  }

  return payload
}

/** Every request is bounded so the UI never hangs forever. */
function withTimeout(promise, ms, message) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(message)), ms),
    ),
  ])
}

export function getHealth() {
  return withTimeout(
    fetch(`${API_BASE}/api/health`, { signal: new AbortController().signal }).then(parse),
    15000,
    'Could not connect to the server.',
  )
}

export function uploadReport(file, onProgress) {
  const form = new FormData()
  form.append('file', file)

  // XHR gives real upload progress, which fetch cannot.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/api/reports/upload`)
    xhr.responseType = 'json'

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    })

    xhr.addEventListener('load', () => {
      const payload = xhr.response
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload)
        return
      }
      if (xhr.status >= 500) {
        // The API itself failed, so the file is not the problem. Say so
        // instead of blaming the report the user just picked.
        reject(
          new Error(
            'The server is not responding. Check that it is running, then try again.',
          ),
        )
        return
      }
      const detail =
        payload?.detail ??
        payload?.message ??
        'The file could not be uploaded. Please try again.'
      reject(new Error(typeof detail === 'string' ? detail : 'The file could not be uploaded.'))
    })

    xhr.addEventListener('error', () =>
      reject(new Error('Could not connect to the server. Check that it is running.')),
    )
    xhr.addEventListener('abort', () => reject(new Error('Upload cancelled.')))

    xhr.send(form)
  })
}

export function analyzeReport(reportId) {
  return withTimeout(
    fetch(`${API_BASE}/api/reports/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ report_id: reportId }),
    }).then(parse),
    180000,
    'Analysis timed out. Please try again.',
  )
}

export function getReport(reportId) {
  return withTimeout(
    fetch(`${API_BASE}/api/reports/${reportId}`).then(parse),
    20000,
    'Results could not be loaded.',
  )
}

export function deleteReport(reportId) {
  return withTimeout(
    fetch(`${API_BASE}/api/reports/${reportId}`, { method: 'DELETE' }).then(parse),
    15000,
    'The report could not be deleted.',
  )
}

/**
 * Read a report and return the text exactly as the reader made it.
 *
 * Nothing is interpreted and no AI is called: this is the raw reading, with
 * the measurements that explain it.
 */
export function readReportText(file) {
  const form = new FormData()
  form.append('file', file)

  return withTimeout(
    fetch(`${API_BASE}/api/reports/read-text`, { method: 'POST', body: form }).then(parse),
    180000,
    'The report text could not be read.',
  )
}
