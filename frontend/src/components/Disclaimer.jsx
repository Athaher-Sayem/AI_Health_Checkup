export default function Disclaimer({ aiNotice }) {
  return (
    <aside className="disclaimer">
      <h2 className="disclaimer-title">A little clarity, not a diagnosis.</h2>
      <p className="disclaimer-text">
        This tool explains report information for educational purposes. It does not
        diagnose conditions or replace medical care. Always discuss your results
        with a qualified healthcare professional.
      </p>
      {aiNotice ? <p className="disclaimer-note">{aiNotice}</p> : null}
    </aside>
  )
}
