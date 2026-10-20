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
  const [progress, setProgress] = useState(6)
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    let cancelled = false
    const stepTimer = setInterval(() => {
      setActiveStep((prev) => (prev < STEPS.length - 1 ? prev + 1 : prev))
    }, 1500)

    // Creeps toward 90% and waits for the real response to finish the job.
    const progressTimer = setInterval(() => {
      setProgress((p) => (p < 90 ? p + (90 - p) * 0.08 : p))
    }, 350)

    analyzeReport(reportId)
      .then(() => {
        clearInterval(stepTimer)
        clearInterval(progressTimer)
        setProgress(100)
        setActiveStep(STEPS.length)
        if (!cancelled) setTimeout(onDone, 350)
      })
      .catch((err) => {
        clearInterval(stepTimer)
        clearInterval(progressTimer)
        if (cancelled) return
        setError(err.message)
      })

    return () => {
      cancelled = true
      clearInterval(stepTimer)
      clearInterval(progressTimer)
    }
  }, [reportId, onDone])

  if (error) {
    return (
      <main className="shell">
        <div className="empty-state" style={{ paddingTop: 'var(--space-16)' }}>
          <h2>রিপোর্ট বিশ্লেষণ করা যায়নি</h2>
          <p className="error-text" style={{ marginTop: 'var(--space-3)' }}>
            {error}
          </p>
          <div className="btn-row" style={{ justifyContent: 'center' }}>
            <button type="button" className="btn btn--primary" onClick={onFailed}>
              আবার চেষ্টা করুন
            </button>
            <button type="button" className="btn btn--secondary" onClick={onCancel}>
              ফিরে যান
            </button>
          </div>
        </div>
      </main>
    )
  }

  return (
    <main className="shell">
      <header className="hero" style={{ paddingBottom: 'var(--space-4)' }}>
        <h1>রিপোর্ট বিশ্লেষণ করা হচ্ছে…</h1>
      </header>

      <div className="progress" role="status" aria-live="polite">
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <div className="progress-meta">
          <span>{STEPS[Math.min(activeStep, STEPS.length - 1)]}</span>
          <span className="progress-percent">{Math.round(progress)}%</span>
        </div>
      </div>

      <ul className="steps">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className={
              index < activeStep
                ? 'step step--done'
                : index === activeStep
                  ? 'step step--active'
                  : 'step'
            }
          >
            <span className="step-mark" aria-hidden="true">
              {index < activeStep ? '✓' : index + 1}
            </span>
            {step}
          </li>
        ))}
      </ul>

      <div className="btn-row">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          বাতিল করুন
        </button>
      </div>
    </main>
  )
}
