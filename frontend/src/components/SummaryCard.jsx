import { formatNumber } from '../utils/numbers.js'

export default function SummaryCard({ summary, counts }) {
  if (!summary) return null

  return (
    <section className="summary">
      <h2 className="summary-title">{summary.headline}</h2>

      <div className="summary-counts">
        <div className="count count--normal">
          <span className="count-value">{formatNumber(counts?.normal)}</span>
          <span className="count-label">Normal</span>
        </div>
        <div className="count count--outside">
          <span className="count-value">{formatNumber(counts?.low)}</span>
          <span className="count-label">Low</span>
        </div>
        <div className="count count--high">
          <span className="count-value">{formatNumber(counts?.high)}</span>
          <span className="count-label">High</span>
        </div>
        <div className="count count--outside">
          <span className="count-value">{formatNumber(counts?.abnormal)}</span>
          <span className="count-label">Abnormal</span>
        </div>
        <div className="count count--unknown">
          <span className="count-value">{formatNumber(counts?.unknown)}</span>
          <span className="count-label">Unable to determine</span>
        </div>
      </div>

      {summary.bullets?.length ? (
        <ul className="summary-bullets">
          {summary.bullets.map((bullet, index) => (
            <li key={index}>{bullet}</li>
          ))}
        </ul>
      ) : null}

      {summary.important_note ? (
        <p className="summary-note">{summary.important_note}</p>
      ) : null}
    </section>
  )
}
