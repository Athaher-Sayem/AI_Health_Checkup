import { useEffect, useRef, useState } from 'react'
import { analyzeReport } from '../services/api.js'

const STEPS = [
  'রিপোর্ট পড়া হচ্ছে',
  'পরীক্ষাগুলো শনাক্ত করা হচ্ছে',
  'ফলাফল যাচাই করা হচ্ছে',
  'সহজ ভাষায় ব্যাখ্যা তৈরি হচ্ছে',
]

export default function ProcessingPage({ reportId, onDone, onFailed, onCancel }) {
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState(8)
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    let cancelled = false
    const stepTimer = setInterval(() => {
      setActiveStep((prev) => (prev < STEPS.length - 1 ? prev + 1 : prev))
    }, 1200)
    const progTimer = setInterval(() => {
      setProgress((p) => (p < 92 ? p + Math.random() * 6 : p))
    }, 400)

    analyzeReport(reportId)
      .then(() => {
        clearInterval(stepTimer); clearInterval(progTimer)
        setProgress(100)
        if (!cancelled) setTimeout(onDone, 300)
      })
      .catch((err) => {
        clearInterval(stepTimer); clearInterval(progTimer)
        if (cancelled) return
        setError(err.message)
      })

    return () => {
      cancelled = true
      clearInterval(stepTimer)
      clearInterval(progTimer)
    }
  }, [reportId, onDone])

  if (error) {
    return (
      <main className="page">
        <h1>রিপোর্ট বিশ্লেষণ করা যায়নি</h1>
        <p className="error">{error}</p>
        <button className="button" onClick={onFailed}>আবার চেষ্টা করুন</button>
      </main>
    )
  }

  return (
    <main className="page">
      <h1>রিপোর্ট বিশ্লেষণ করা হচ্ছে…</h1>
      <div style={{
        height: 8, background: 'var(--surface-2)', borderRadius: 999,
        overflow: 'hidden', margin: 'var(--space-4) 0 var(--space-6)',
      }}>
        <div style={{
          height: '100%', width: progress + '%',
          background: 'var(--accent)', borderRadius: 999,
          transition: 'width 300ms ease-out',
        }} />
      </div>
      <ul className="steps" style={{ listStyle: 'none', padding: 0 }}>
        {STEPS.map((step, index) => (
          <li
            key={step}
            style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
              padding: 'var(--space-2) 0',
              color: index <= activeStep ? 'var(--text)' : 'var(--text-muted)',
            }}
          >
            <span style={{
              width: 22, height: 22, borderRadius: '50%',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 'var(--fs-12)', fontWeight: 600,
              background: index < activeStep ? 'var(--accent)' : 'var(--surface-2)',
              color: index < activeStep ? '#fff' : 'var(--text-muted)',
              border: '1px solid var(--border)',
            }}>
              {index < activeStep ? '✓' : index + 1}
            </span>
            {step}
          </li>
        ))}
      </ul>
      <button className="button button--ghost" onClick={onCancel} style={{ marginTop: 'var(--space-4)' }}>
        বাতিল করুন
      </button>
    </main>
  )
}