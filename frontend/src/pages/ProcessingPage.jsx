import { useEffect, useRef, useState } from 'react'
import { useRequest } from '../hooks/useRequest.js'
import { analyzeReport } from '../services/api.js'

const STEPS = [
  'Reading your report',
  'Identifying test results',
  'Verifying values and reference ranges',
  'Preparing plain-English explanations',
]

export default function ProcessingPage({ reportId, onDone, onFailed, onCancel }) {
  const [activeStep, setActiveStep] = useState(0)
  const [progress, setProgress] = useState(6)
  const finished = useRef(false)

  const { error, loading } = useRequest(() => analyzeReport(reportId), [reportId])

  // The step list and the progress bar advance on their own until the real
  // response arrives, so the screen never looks stuck.
  useEffect(() => {
    const stepTimer = setInterval(() => {
      setActiveStep((prev) => (prev < STEPS.length - 1 ? prev + 1 : prev))
    }, 1500)

    const progressTimer = setInterval(() => {
      setProgress((p) => (p < 90 ? p + (90 - p) * 0.08 : p))
    }, 350)

    return () => {
      clearInterval(stepTimer)
      clearInterval(progressTimer)
    }
  }, [])

  useEffect(() => {
    if (loading || error || finished.current) return
    finished.current = true
    setProgress(100)
    setActiveStep(STEPS.length)
    const timer = setTimeout(onDone, 400)
    return () => clearTimeout(timer)
  }, [loading, error, onDone])

  if (error) {
    return (
      <main className="shell processing-shell" id="main-content" tabIndex={-1}>
        <div className="empty-state" style={{ paddingTop: 'var(--space-16)' }}>
          <h2>Unable to analyse your report</h2>
          <p className="error-text" style={{ marginTop: 'var(--space-3)' }}>
            {error.message}
          </p>
          <div className="btn-row" style={{ justifyContent: 'center' }}>
            <button type="button" className="btn btn--primary" onClick={onFailed}>
              Try again
            </button>
            <button type="button" className="btn btn--secondary" onClick={onCancel}>
              Go back
            </button>
          </div>
        </div>
      </main>
    )
  }

  return (
    <main className="shell processing-shell" id="main-content" tabIndex={-1}>
      <header className="hero" style={{ paddingBottom: 'var(--space-4)' }}>
        <span className="processing-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4" /></svg></span>
        <h1>Making sense of your report.</h1>
        <p className="hero-tagline">Checking the facts before explaining them. This may take a moment.</p>
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
          Go back
        </button>
      </div>
    </main>
  )
}
