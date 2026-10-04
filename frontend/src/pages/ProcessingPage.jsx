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
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    let cancelled = false
    const timer = setInterval(() => {
      setActiveStep((prev) => (prev < STEPS.length - 1 ? prev + 1 : prev))
    }, 1200)

    analyzeReport(reportId)
      .then(() => {
        clearInterval(timer)
        if (!cancelled) onDone()
      })
      .catch((err) => {
        clearInterval(timer)
        if (cancelled) return
        setError(err.message)
      })

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [reportId, onDone])

  if (error) {
    return (
      <main className="page">
        <h1>রিপোর্ট বিশ্লেষণ করা যায়নি</h1>
        <p className="error">{error}</p>
        <button className="button" onClick={onFailed}>
          আবার চেষ্টা করুন
        </button>
      </main>
    )
  }

  return (
    <main className="page">
      <h1>রিপোর্ট বিশ্লেষণ করা হচ্ছে…</h1>
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
            <span className="step-mark">
              {index < activeStep ? '✓' : index === activeStep ? '○' : '○'}
            </span>
            {step}
          </li>
        ))}
      </ul>
      <button className="button button--ghost" onClick={onCancel}>
        বাতিল করুন
      </button>
    </main>
  )
}
