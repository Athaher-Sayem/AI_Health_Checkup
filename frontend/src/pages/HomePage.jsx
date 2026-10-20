import { useEffect, useRef, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import { useLocale } from '../context/LocaleContext.jsx'
import { uploadReport } from '../services/api.js'

//: Used until the server reports which formats it accepts.
const DEFAULT_TYPES = ['pdf', 'jpg', 'jpeg', 'png', 'webp']

//: Used until the server reports which of them are read as images.
const DEFAULT_IMAGE_TYPES = ['jpg', 'jpeg', 'png', 'webp']

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

  // The server owns the list of accepted formats and which of them are
  // images, so the picker cannot drift away from what the API accepts.
  const reported = Array.isArray(health?.supported_types)
    ? health.supported_types.filter(
        (type) => typeof type === 'string' && type.trim(),
      )
    : []
  const acceptedTypes = reported.length ? reported : DEFAULT_TYPES
  const reportedImages = Array.isArray(health?.image_types)
    ? health.image_types.filter((type) => typeof type === 'string' && type.trim())
    : []
  const imageTypes = reportedImages.length ? reportedImages : DEFAULT_IMAGE_TYPES
  const accepted = acceptedTypes.map((type) => `.${type}`).join(',')
  const filePattern = new RegExp(
    `\\.(${acceptedTypes.map(escapePattern).join('|')})$`,
    'i',
  )
  const imagePattern = new RegExp(
    `\\.(${imageTypes.map(escapePattern).join('|')})$`,
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
    if (!file || busy) return
    setError(null)

    const lower = file.name.toLowerCase()
    if (!filePattern.test(lower)) {
      setError(`Only ${acceptedTypes.map((type) => type.toUpperCase()).join(', ')} files are accepted.`)
      return
    }
    if (file.size > maxSizeMb * 1024 * 1024) {
      setError(`The file is too large. The maximum size is ${maxSizeMb} MB.`)
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
    <main className="shell home-shell" id="main-content" tabIndex={-1}>
      <div className="home-workspace">
      <header className="hero home-intro">
        <span className="intro-tag"><span aria-hidden="true" /> A clearer view of your health</span>
        <h1>Your report, made clear.</h1>
        <p className="hero-tagline">{t('tagline')}</p>
        <ol className="how-it-works" aria-label="How it works">
          <li><span className="how-step" aria-hidden="true">1</span><div><h2>Upload your report</h2><p>A lab report PDF or a clear photo is all you need.</p></div></li>
          <li><span className="how-step" aria-hidden="true">2</span><div><h2>See the verified results</h2><p>Values are checked against the ranges printed on your report.</p></div></li>
          <li><span className="how-step" aria-hidden="true">3</span><div><h2>Understand what they mean</h2><p>Read plain-English explanations, then talk with your doctor.</p></div></li>
        </ol>
      </header>

      <section className="uploader upload-panel" aria-labelledby="upload-heading">
        <div className="upload-panel-heading"><span className="panel-doc" aria-hidden="true"><DocIcon /></span><div><h2 id="upload-heading">Start with your report</h2><p>No medical jargon. Just a clearer explanation.</p></div></div>
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
          aria-label="Choose a report to analyse"
          aria-describedby="upload-formats"
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
          <span className="btn btn--primary browse-action" aria-hidden="true">Browse files</span>
          <p className="dropzone-meta" id="upload-formats">
            {acceptedTypes.map((type) => type.toUpperCase()).join(', ')} · Up to{' '}
            {maxSizeMb} MB
          </p>
          <input
            ref={inputRef}
            type="file"
            aria-label="Report file"
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
              <span>Uploading your report…</span>
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
              Reset upload
            </button>
          </div>
        ) : null}
        <p className="upload-footnote"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" /></svg>Stored temporarily. Delete your report when you’re done.</p>
      </section>
      </div>

      <section className="report-guidance" aria-label="Before you upload">
        <div><h2>Better input. Clearer results.</h2><p>Use the original PDF when possible. For photos, keep the whole page in focus with good lighting and no glare.</p></div>
        <div><h2>Your report is the source.</h2><p>We use the reference ranges on your document. Missing or unclear information is marked as uncertain, never guessed.</p></div>
      </section>

      <Disclaimer
        aiNotice={
          health && health.ai_configured === false
            ? 'AI explanations are not enabled. You can still view verified results read from your report.'
            : null
        }
      />
    </main>
  )
}
