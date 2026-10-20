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
    'সার্ভারের সাথে সংযোগ করা যায়নি।',
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
      const detail =
        payload?.detail ??
        payload?.message ??
        'ফাইলটি আপলোড করা যায়নি। আবার চেষ্টা করুন।'
      reject(new Error(typeof detail === 'string' ? detail : 'ফাইলটি আপলোড করা যায়নি।'))
    })

    xhr.addEventListener('error', () =>
      reject(new Error('সার্ভারের সাথে সংযোগ করা যায়নি। সার্ভার চালু আছে কি না দেখুন।')),
    )
    xhr.addEventListener('abort', () => reject(new Error('আপলোড বাতিল করা হয়েছে।')))

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
    'বিশ্লেষণে অনেক সময় লেগেছে। আবার চেষ্টা করুন।',
  )
}

export function getReport(reportId) {
  return withTimeout(
    fetch(`${API_BASE}/api/reports/${reportId}`).then(parse),
    20000,
    'ফলাফল আনা যায়নি।',
  )
}

export function deleteReport(reportId) {
  return withTimeout(
    fetch(`${API_BASE}/api/reports/${reportId}`, { method: 'DELETE' }).then(parse),
    15000,
    'রিপোর্ট মুছে ফেলা যায়নি।',
  )
}
