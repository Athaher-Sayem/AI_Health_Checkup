import { useEffect, useRef, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import { useLocale } from '../context/LocaleContext.jsx'
import { uploadReport } from '../services/api.js'

//: Used until the server reports which formats it accepts.
const DEFAULT_TYPES = ['pdf', 'jpg', 'jpeg', 'png', 'webp']

/** Escape a file type so it is safe inside a regular expression. */
function escapePattern(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const UploadIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 16V4M8 8l4-4 4 4" />
    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
  </svg>
)

const DocIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
  </svg>
)

export default function HomePage({ health, maxSizeMb, onUploaded }) {
  const { t } = useLocale()
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [preview, setPreview] = useState(null)
  const inputRef = useRef(null)
  const objectUrl = useRef(null)

  // The server owns the list of accepted formats, so the picker cannot drift
  // away from what the API actually accepts.
  const acceptedTypes =
    health?.supported_types?.length ? health.supported_types : DEFAULT_TYPES
  const accepted = acceptedTypes.map((type) => `.${type}`).join(',')
  const filePattern = new RegExp(
    `\\.(${acceptedTypes.map(escapePattern).join('|')})$`,
    'i',
  )
  const imagePattern = new RegExp(
    `\\.(${acceptedTypes
      .filter((type) => type !== 'pdf')
      .map(escapePattern)
      .join('|')})$`,
    'i',
  )

  useEffect(() => {
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    }
  }, [])

  function reset() {
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current)
      objectUrl.current = null
    }
    setPreview(null)
    setUploadPct(0)
    setError(null)
    setBusy(false)
  }

  async function handleFile(file) {
    if (!file) return
    setError(null)

    const lower = file.name.toLowerCase()
    if (!filePattern.test(lower)) {
      setError(`শুধুমাত্র ${acceptedTypes.map((type) => type.toUpperCase()).join(', ')} ফাইল দেওয়া যাবে।`)
      return
    }
    if (file.size > maxSizeMb * 1024 * 1024) {
      setError(`ফাইলের আকার অনেক বড়। সর্বোচ্চ ${maxSizeMb} MB নেওয়া যাবে।`)
      return
    }

    const isImage = imagePattern.test(lower)
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = isImage ? URL.createObjectURL(file) : null

    setPreview({
      name: file.name,
      size: `${(file.size / 1024).toFixed(0)} KB`,
      isImage,
      url: objectUrl.current,
    })
    setUploadPct(0)
    setBusy(true)

    try {
      const result = await uploadReport(file, setUploadPct)
      setUploadPct(100)
      onUploaded(result.report_id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <h1>{t('app_title')}</h1>
        <p className="hero-tagline">{t('tagline')}</p>
      </header>

      <section className="uploader">
        <div
          className={`dropzone${dragging ? ' dropzone--active' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            handleFile(e.dataTransfer.files?.[0])
          }}
          onClick={() => !busy && inputRef.current?.click()}
          role="button"
          tabIndex={0}
          aria-disabled={busy}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ' ') && !busy) {
              e.preventDefault()
              inputRef.current?.click()
            }
          }}
        >
          <span className="dropzone-icon" aria-hidden="true">
            <UploadIcon />
          </span>
          <p className="dropzone-title">{t('upload_title')}</p>
          <p className="dropzone-hint">{t('upload_hint')}</p>
          <p className="dropzone-meta">
            {acceptedTypes.map((type) => type.toUpperCase()).join(', ')} — সর্বোচ্চ{' '}
            {maxSizeMb} MB
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={accepted}
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>

        {preview ? (
          <div className="file-preview">
            {preview.isImage ? (
              <img className="file-preview-thumb" src={preview.url} alt="" />
            ) : (
              <span className="file-preview-thumb file-preview-thumb--icon" aria-hidden="true">
                <DocIcon />
              </span>
            )}
            <div style={{ minWidth: 0 }}>
              <div className="file-preview-name">{preview.name}</div>
              <div className="file-preview-meta">{preview.size}</div>
            </div>
          </div>
        ) : null}

        {busy ? (
          <div className="progress" role="status" aria-live="polite">
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${uploadPct || 8}%` }}
              />
            </div>
            <div className="progress-meta">
              <span>ফাইল আপলোড হচ্ছে…</span>
              <span className="progress-percent">{uploadPct}%</span>
            </div>
          </div>
        ) : null}

        {error ? (
          <p className="error-text" role="alert" style={{ marginTop: 'var(--space-4)' }}>
            {error}
          </p>
        ) : null}

        {busy ? (
          <div className="btn-row">
            <button type="button" className="btn btn--ghost" onClick={reset}>
              বাতিল করুন
            </button>
          </div>
        ) : null}
      </section>

      <Disclaimer
        aiNotice={
          health && health.ai_configured === false
            ? 'AI ব্যাখ্যা চালু নেই। ফলাফলগুলো শুধু রিপোর্টের লেখা থেকে দেখানো হচ্ছে।'
            : null
        }
      />
    </main>
  )
}
