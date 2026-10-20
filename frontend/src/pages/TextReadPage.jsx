import { useRef, useState } from 'react'
import { useLocale } from '../context/LocaleContext.jsx'
import { readReportText } from '../services/api.js'

/**
 * The raw reading of a report.
 *
 * This screen shows exactly what the reader made of a file - the text, where
 * it came from and how legible the picture was - without interpreting a
 * single value. It is the place to see why a report did or did not produce
 * results.
 */

const DEFAULT_TYPES = ['pdf', 'jpg', 'jpeg', 'png', 'webp']

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined) return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number.toFixed(digits)
}

function Measurement({ label, value }) {
  return (
    <div className="measure">
      <span className="measure-label">{label}</span>
      <span className="measure-value">{value}</span>
    </div>
  )
}

export default function TextReadPage() {
  const { t } = useLocale()
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  function reset() {
    setFile(null)
    setResult(null)
    setError(null)
    setBusy(false)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleFile(chosen) {
    if (!chosen) return
    setError(null)
    setResult(null)
    setFile(chosen)
    setBusy(true)
    try {
      const payload = await readReportText(chosen)
      setResult(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <h1>{t('read_text_title')}</h1>
        <p className="hero-tagline">{t('read_text_tagline')}</p>
      </header>

      <section className="uploader">
        <div
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
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
          <p className="dropzone-title">{t('read_text_pick')}</p>
          <p className="dropzone-hint">{t('read_text_hint')}</p>
          <p className="dropzone-meta">
            {DEFAULT_TYPES.map((type) => type.toUpperCase()).join(', ')}
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={DEFAULT_TYPES.map((type) => `.${type}`).join(',')}
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>

        {busy ? (
          <div className="progress" role="status" aria-live="polite">
            <div className="progress-track">
              <div className="progress-fill" style={{ width: '45%' }} />
            </div>
            <div className="progress-meta">
              <span>{t('reading')}</span>
            </div>
          </div>
        ) : null}

        {error ? (
          <p className="error-text" role="alert" style={{ marginTop: 'var(--space-4)' }}>
            {error}
          </p>
        ) : null}

        {result ? (
          <div className="btn-row">
            <button type="button" className="btn btn--ghost" onClick={reset}>
              {t('read_text_again')}
            </button>
          </div>
        ) : null}
      </section>

      {result ? (
        <section className="group">
          <h2 className="group-title">
            {result.filename}
            <span className="badge">{result.kind}</span>
          </h2>

          <div className="measures">
            <Measurement label={t('measure_pages')} value={result.pages.length} />
            <Measurement label={t('measure_rows')} value={result.total_rows} />
            <Measurement
              label={t('measure_characters')}
              value={result.pages.reduce((sum, page) => sum + page.characters, 0)}
            />
          </div>

          {result.warnings?.length ? (
            <div className="warning-list" role="status">
              {result.warnings.map((warning, index) => (
                <p key={index} className="warning-item">
                  {warning}
                </p>
              ))}
            </div>
          ) : null}

          {result.pages.map((page) => (
            <div key={page.page} className="read-page">
              <div className="read-page-head">
                <h3 className="read-page-title">
                  {t('page_label')} {page.page}
                </h3>
                <span className="badge">{page.source}</span>
                <span className="badge">
                  {t('measure_rows')}: {page.parsed_rows}
                </span>
              </div>

              <div className="measures">
                <Measurement label={t('measure_characters')} value={page.characters} />
                <Measurement label={t('measure_lines')} value={page.lines} />
                {page.word_count !== null && page.word_count !== undefined ? (
                  <Measurement label={t('measure_words')} value={page.word_count} />
                ) : null}
                {page.median_text_height_px ? (
                  <Measurement
                    label={t('measure_text_height')}
                    value={`${formatNumber(page.median_text_height_px)} px`}
                  />
                ) : null}
                {page.median_word_confidence ? (
                  <Measurement
                    label={t('measure_confidence')}
                    value={formatNumber(page.median_word_confidence, 0)}
                  />
                ) : null}
                {page.legible !== null && page.legible !== undefined ? (
                  <Measurement
                    label={t('measure_legible')}
                    value={page.legible ? t('yes') : t('no')}
                  />
                ) : null}
              </div>

              <pre className="read-text" tabIndex={0}>
                {page.text || t('read_text_empty')}
              </pre>

              {page.raw_text ? (
                <details className="read-raw">
                  <summary>{t('read_text_raw')}</summary>
                  <pre className="read-text" tabIndex={0}>
                    {page.raw_text}
                  </pre>
                </details>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}
    </main>
  )
}
