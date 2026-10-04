export default function SummaryCard({ summary, counts }) {
  if (!summary) return null

  return (
    <section className="summary">
      <h2 className="summary-title">{summary.headline}</h2>
      <div className="summary-counts">
        <div className="count count--normal">
          <span className="count-value">{counts?.normal ?? 0}</span>
          <span className="count-label">স্বাভাবিক</span>
        </div>
        <div className="count count--outside">
          <span className="count-value">{counts?.low ?? 0}</span>
          <span className="count-label">কম</span>
        </div>
        <div className="count count--high">
          <span className="count-value">{counts?.high ?? 0}</span>
          <span className="count-label">বেশি</span>
        </div>
        <div className="count count--unknown">
          <span className="count-value">{counts?.unknown ?? 0}</span>
          <span className="count-label">নির্ধারণ করা যায়নি</span>
        </div>
      </div>

      {summary.bullets?.length ? (
        <ul className="summary-bullets">
          {summary.bullets.map((bullet, index) => (
            <li key={index}>{bullet}</li>
          ))}
        </ul>
      ) : null}

      <p className="summary-note">{summary.important_note}</p>
    </section>
  )
}
