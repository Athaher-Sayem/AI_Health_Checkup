import { useRef, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import { useLocale } from '../context/LocaleContext.jsx'
import { uploadReport } from '../services/api.js'

const ACCEPTED = '.pdf,.jpg,.jpeg,.png'

export default function HomePage({ health, maxSizeMb, onUploaded }) {
  const { t } = useLocale()
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null)
  const inputRef = useRef(null)

  async function handleFile(file) {
    if (!file) return
    setError(null)
    const lower = file.name.toLowerCase()
    if (!/\.(pdf|jpe?g|png)$/.test(lower)) {
      setError('শুধুমাত্র PDF, JPG, JPEG বা PNG ফাইল দেওয়া যাবে।')
      return
    }
    if (file.size > maxSizeMb * 1024 * 1024) {
      setError(`ফাইলের আকার অনেক বড়। সর্বোচ্চ ${maxSizeMb} MB নেওয়া যাবে।`)
      return
    }
    setPreview({ name: file.name, size: (file.size / 1024).toFixed(1) + ' KB', isImage: /\.(jpe?g|png)$/.test(lower), url: /\.(jpe?g|png)$/.test(lower) ? URL.createObjectURL(file) : null })
    setBusy(true)
    try {
      const result = await uploadReport(file)
      onUploaded(result.report_id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <header className="hero">
        <h1>{t('app_title')}</h1>
        <p className="tagline">{t('tagline')}</p>
      </header>

      <section className="uploader">
        <div
          className={`dropzone${dragging ? ' dropzone--active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files?.[0]) }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click() }}
        >
          <p className="dropzone-title">{t('upload_title')}</p>
          <p className="dropzone-hint">{t('upload_hint')}</p>
          <p className="dropzone-meta">PDF, JPG, JPEG, PNG — max {maxSizeMb} MB</p>
          <input ref={inputRef} type="file" accept={ACCEPTED} hidden onChange={(e) => handleFile(e.target.files?.[0])} />
        </div>

        {preview && (
          <div className="card" style={{ marginTop: 'var(--space-3)', display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
            {preview.url && <img src={preview.url} alt="preview" style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 'var(--radius-sm)', outline: '1px solid rgba(0,0,0,0.1)' }} />}
            <div>
              <div className="test-name">{preview.name}</div>
              <div className="muted">{preview.size}</div>
            </div>
          </div>
        )}

        {busy ? <p className="status muted" style={{ marginTop: 'var(--space-3)' }}>Uploading…</p> : null}
        {error ? <p className="error" style={{ marginTop: 'var(--space-3)' }}>{error}</p> : null}
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