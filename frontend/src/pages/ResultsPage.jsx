import { useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import SummaryCard from '../components/SummaryCard.jsx'
import TestCard from '../components/TestCard.jsx'
import { useLocale } from '../context/LocaleContext.jsx'
import { useRequest } from '../hooks/useRequest.js'
import { toBanglaNumber } from '../utils/numbers.js'
import { deleteReport, getReport } from '../services/api.js'

const PrintIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6 9V3h12v6" />
    <path d="M6 18H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2" />
    <rect x="6" y="14" width="12" height="7" rx="1" />
  </svg>
)

const CopyIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
)

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
  </svg>
)

export default function ResultsPage({ reportId, onReset }) {
  const { t } = useLocale()
  const [deleted, setDeleted] = useState(false)
  const [copied, setCopied] = useState(false)

  const { data, error, loading } = useRequest(() => getReport(reportId), [reportId])

  async function handleDelete() {
    try { await deleteReport(reportId) } catch { /* best-effort */ }
    setDeleted(true)
  }

  function handlePrint() {
    window.print()
  }

  function handleCopy() {
    if (!data) return
    const bullets = data.summary?.bullets ?? []
    const text = [data.summary?.headline, ...bullets, data.summary?.important_note]
      .filter(Boolean)
      .join('\n')
    if (!navigator.clipboard) return
    navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1800)
      },
      () => {},
    )
  }

  if (error) {
    return (
      <main className="shell">
        <div className="empty-state" style={{ paddingTop: 'var(--space-16)' }}>
          <h2>ফলাফল দেখানো যায়নি</h2>
          <p className="error-text" style={{ marginTop: 'var(--space-3)' }}>
            {error.message}
          </p>
          <div className="btn-row" style={{ justifyContent: 'center' }}>
            <button type="button" className="btn btn--primary" onClick={onReset}>
              {t('new_report')}
            </button>
          </div>
        </div>
      </main>
    )
  }

  if (deleted) {
    return (
      <main className="shell">
        <div className="empty-state" style={{ paddingTop: 'var(--space-16)' }}>
          <h2>রিপোর্ট মুছে ফেলা হয়েছে</h2>
          <p className="muted" style={{ marginTop: 'var(--space-3)' }}>
            আপলোড করা ফাইল ও ফলাফল সার্ভার থেকে মুছে ফেলা হয়েছে।
          </p>
          <div className="btn-row" style={{ justifyContent: 'center' }}>
            <button type="button" className="btn btn--primary" onClick={onReset}>
              {t('new_report')}
            </button>
          </div>
        </div>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="shell">
        <div className="progress" style={{ marginTop: 'var(--space-12)' }}>
          <div className="progress-track">
            <div className="progress-fill progress-fill--indeterminate" />
          </div>
          <div className="progress-meta">
            <span>{t('loading')}</span>
          </div>
        </div>
      </main>
    )
  }
  const groups = data.groups ?? {}
  const explanationsByName = new Map(
    (data.explanations ?? []).map((item) => [item.test_name, item]),
  )
  const counts = data.counts ?? {}
  const total = Math.max(counts.total ?? 0, 1)
  const outside = (counts.low ?? 0) + (counts.high ?? 0) + (counts.abnormal ?? 0)
  const segments = [
    { key: 'normal', label: 'স্বাভাবিক', value: counts.normal ?? 0 },
    { key: 'outside', label: 'সীমার বাইরে', value: outside },
    { key: 'unknown', label: 'নির্ধারণ করা যায়নি', value: counts.unknown ?? 0 },
  ]

  return (
    <main className="shell">
      <header className="hero" style={{ paddingBottom: 'var(--space-4)' }}>
        <h1>{t('results_title')}</h1>
        <p className="hero-tagline" style={{ fontSize: 'var(--fs-14)' }}>
          ফাইল: {data.filename} ·{' '}
          {data.meta?.ocr_used ? 'OCR দিয়ে পড়া হয়েছে' : 'টেক্সট থেকে পড়া হয়েছে'} ·{' '}
          {data.meta?.page_count} পৃষ্ঠা
        </p>
      </header>

      <section className="verdict" aria-label="ফলাফলের সারসংক্ষেপ">
        <div className="verdict-strip" role="img" aria-label="ফলাফলের বিভাজন">
          {segments.map((seg) =>
            seg.value > 0 ? (
              <span
                key={seg.key}
                className={`verdict-seg verdict-seg--${seg.key}`}
                style={{ width: `${(seg.value / total) * 100}%` }}
              />
            ) : null,
          )}
        </div>
        <div className="verdict-legend">
          {segments.map((seg) => (
            <span className="verdict-key" key={seg.key}>
              <span
                className="verdict-dot"
                style={{ background: `var(--${seg.key === 'normal' ? 'ok' : seg.key === 'outside' ? 'warn' : 'unknown'})` }}
                aria-hidden="true"
              />
              {seg.label}
              <span className="verdict-count">{toBanglaNumber(seg.value)}</span>
            </span>
          ))}
        </div>
      </section>

      <SummaryCard summary={data.summary} counts={data.counts} />

      {data.ai_error ? (
        <p className="notice">
          AI ব্যাখ্যা যোগ করা যায়নি ({data.ai_error})। নিচের ফলাফলগুলো রিপোর্টের লেখা
          থেকে সরাসরি দেখানো হয়েছে।
        </p>
      ) : null}

      {data.validation?.contradictions?.length ? (
        <p className="notice">
          AI ব্যাখ্যায় অসামঞ্জস্য পাওয়া গিয়েছিল, তাই সঠিক তথ্য দিয়ে আবার তৈরি করা হয়েছে।
        </p>
      ) : null}

      {Object.entries(groups).map(([groupName, items]) =>
        items.length ? (
          <section key={groupName} className="group">
            <h2 className="group-title">
              {groupName}
              <span className="group-count">{toBanglaNumber(items.length)}</span>
            </h2>
            {items.map((item, index) => (
              <TestCard
                key={`${item.test_name}-${item.source_page}-${index}`}
                result={item}
                explanation={explanationsByName.get(item.test_name)}
              />
            ))}
          </section>
        ) : null,
      )}

      {!data.results?.length ? (
        <div className="empty-state">
          <h2>কোনো ফলাফল পাওয়া যায়নি</h2>
          <p className="muted" style={{ marginTop: 'var(--space-2)' }}>
            রিপোর্টে পরীক্ষার ফলাফল চেনা যায়নি। ফাইলটির মান বেশি হলে OCR সাহায্যে দরকার
            হতে পারে।
          </p>
        </div>
      ) : null}

      <Disclaimer />

      <div className="btn-row">
        <button type="button" className="btn btn--primary" onClick={onReset}>
          {t('new_report')}
        </button>
        <button type="button" className="btn btn--secondary" onClick={handlePrint}>
          <PrintIcon />
          {t('print_pdf')}
        </button>
        <button type="button" className="btn btn--secondary" onClick={handleCopy}>
          <CopyIcon />
          {copied ? 'কপি হয়েছে ✓' : t('copy_summary')}
        </button>
        <button type="button" className="btn btn--danger" onClick={handleDelete}>
          <TrashIcon />
          {t('delete')}
        </button>
      </div>
    </main>
  )
}
