import { useEffect, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import SummaryCard from '../components/SummaryCard.jsx'
import TestCard from '../components/TestCard.jsx'
import { useLocale } from '../context/LocaleContext.jsx'
import { deleteReport, getReport } from '../services/api.js'

export default function ResultsPage({ reportId, onReset }) {
  const { t } = useLocale()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [deleted, setDeleted] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let cancelled = false
    getReport(reportId)
      .then((result) => { if (!cancelled) setData(result) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [reportId])

  async function handleDelete() {
    try { await deleteReport(reportId) } catch { /* best-effort */ }
    setDeleted(true)
  }

  function handlePrint() { window.print() }

  function handleCopy() {
    if (!data) return
    const text = (data.summary?.bullets || []).join('\n')
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  if (error) {
    return (
      <main className="page">
        <h1>ফলাফল দেখানো যায়নি</h1>
        <p className="error">{error}</p>
        <button className="button" onClick={onReset}>{t('new_report')}</button>
      </main>
    )
  }

  if (deleted) {
    return (
      <main className="page">
        <h1>রিপোর্ট মুছে ফেলা হয়েছে</h1>
        <p className="muted">আপলোড করা ফাইল ও ফলাফল সার্ভার থেকে মুছে ফেলা হয়েছে।</p>
        <button className="button" onClick={onReset}>{t('new_report')}</button>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="page">
        <p className="muted">{t('loading')}</p>
      </main>
    )
  }

  const groups = data.groups ?? {}
  const explanationsByName = new Map((data.explanations ?? []).map((item) => [item.test_name, item]))
  const counts = data.counts || {}
  const total = counts.total || 1
  const normalPct = ((counts.normal || 0) / total) * 100
  const outPct = (((counts.low || 0) + (counts.high || 0) + (counts.abnormal || 0)) / total) * 100
  const unknownPct = ((counts.unknown || 0) / total) * 100

  return (
    <main className="page">
      <h1>{t('results_title')}</h1>
      <p className="muted">
        ফাইল: {data.filename} · {data.meta?.ocr_used ? 'OCR দিয়ে পড়া হয়েছে' : 'টেক্সট থেকে পড়া হয়েছে'} ·{' '}
        {data.meta?.page_count} পৃষ্ঠা
      </p>

      <div className="verdict-strip" role="img" aria-label="result distribution">
        <span style={{ width: normalPct + '%', background: 'var(--ok)' }} />
        <span style={{ width: outPct + '%', background: 'var(--warn)' }} />
        <span style={{ width: unknownPct + '%', background: 'var(--unknown)' }} />
      </div>
      <p className="muted" style={{ fontSize: 'var(--fs-12)', marginBottom: 'var(--space-4)' }}>
        স্বাভাবিক {counts.normal || 0} · সীমার বাইরে {(counts.low||0)+(counts.high||0)+(counts.abnormal||0)} · নির্ধারণ করা যায়নি {counts.unknown || 0}
      </p>

      <SummaryCard summary={data.summary} counts={data.counts} />

      {data.ai_error ? (
        <p className="notice">
          AI ব্যাখ্যা যোগ করা যায়নি ({data.ai_error})। নিচের ফলাফলগুলো রিপোর্টের
          লেখা থেকে সরাসরি দেখানো হয়েছে।
        </p>
      ) : null}

      {Object.entries(groups).map(([groupName, items]) =>
        items.length ? (
          <section key={groupName} className="group">
            <h2 className={`group-title group-title--${groupName}`}>
              {groupName} ({items.length})
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
        <p className="muted">
          রিপোর্টে পরীক্ষার ফলাফল চেনা যায়নি। ফাইলটির মান বেশি হলে OCR সাহায্যে দরকার হতে
          পারে।
        </p>
      ) : null}

      <Disclaimer />

      <div className="actions">
        <button className="button button--ghost" onClick={handleDelete}>{t('delete')}</button>
        <button className="button button--ghost" onClick={handleCopy}>{copied ? '✓' : t('copy_summary')}</button>
        <button className="button button--ghost" onClick={handlePrint}>{t('print_pdf')}</button>
        <button className="button" onClick={onReset}>{t('new_report')}</button>
      </div>
    </main>
  )
}