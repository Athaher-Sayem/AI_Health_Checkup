import { useEffect, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import SummaryCard from '../components/SummaryCard.jsx'
import TestCard from '../components/TestCard.jsx'
import { deleteReport, getReport } from '../services/api.js'

export default function ResultsPage({ reportId, onReset }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [deleted, setDeleted] = useState(false)

  useEffect(() => {
    let cancelled = false
    getReport(reportId)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [reportId])

  async function handleDelete() {
    try {
      await deleteReport(reportId)
    } catch {
      // Deleting is best-effort; the record also expires on its own.
    }
    setDeleted(true)
  }

  if (error) {
    return (
      <main className="page">
        <h1>ফলাফল দেখানো যায়নি</h1>
        <p className="error">{error}</p>
        <button className="button" onClick={onReset}>
          নতুন রিপোর্ট আপলোড করুন
        </button>
      </main>
    )
  }

  if (deleted) {
    return (
      <main className="page">
        <h1>রিপোর্ট মুছে ফেলা হয়েছে</h1>
        <p className="muted">আপলোড করা ফাইল ও ফলাফল সার্ভার থেকে মুছে ফেলা হয়েছে।</p>
        <button className="button" onClick={onReset}>
          নতুন রিপোর্ট আপলোড করুন
        </button>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="page">
        <p className="muted">লোড হচ্ছে…</p>
      </main>
    )
  }

  const groups = data.groups ?? {}
  const explanationsByName = new Map(
    (data.explanations ?? []).map((item) => [item.test_name, item]),
  )

  return (
    <main className="page">
      <h1>রিপোর্টের ফলাফল</h1>
      <p className="muted">
        ফাইল: {data.filename} · {data.meta?.ocr_used ? 'OCR দিয়ে পড়া হয়েছে' : 'টেক্সট থেকে পড়া হয়েছে'} ·{' '}
        {data.meta?.page_count} পৃষ্ঠা
      </p>

      <SummaryCard summary={data.summary} counts={data.counts} />

      {data.ai_error ? (
        <p className="notice">
          AI ব্যাখ্যা যোগ করা যায়নি ({data.ai_error})। নিচের ফলাফলগুলো রিপোর্টের
          লেখা থেকে সরাসরি দেখানো হয়েছে।
        </p>
      ) : null}

      {data.validation?.contradictions?.length ? (
        <p className="notice">
          AI ব্যাখ্যায় অসামঞ্জস্য পাওয়া গিয়েছিল, তাই সঠিক তথ্য দিয়ে আবার তৈরি করা
          হয়েছে।
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
        <button className="button button--ghost" onClick={handleDelete}>
          রিপোর্ট মুছে ফেলুন
        </button>
        <button className="button" onClick={onReset}>
          নতুন রিপোর্ট আপলোড করুন
        </button>
      </div>
    </main>
  )
}
