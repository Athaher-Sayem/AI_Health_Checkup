const STATUS_CLASS = {
  normal: 'badge badge--normal',
  low: 'badge badge--low',
  high: 'badge badge--high',
  abnormal: 'badge badge--outside',
  unknown: 'badge badge--unknown',
}

const STATUS_LABEL = {
  normal: 'Normal', low: 'Low', high: 'High',
  abnormal: 'Outside range', unknown: 'Unable to determine',
}

export default function TestCard({ result, explanation }) {
  const valueLabel = [result.value_text, result.unit].filter(Boolean).join(' ')

  return (
    <article className="test-card">
      <header className="test-card-header">
        <h3 className="test-name">{result.test_name}</h3>
        <span className={STATUS_CLASS[result.status] ?? STATUS_CLASS.unknown}>
          {STATUS_LABEL[result.status] ?? STATUS_LABEL.unknown}
        </span>
      </header>

      <p className="test-value">{valueLabel || 'Value unavailable'}</p>

      <p className="test-reference">
        Reference range:{' '}
        {result.reference?.raw_text
          ? result.reference.raw_text
          : 'No reference range printed on the report'}
      </p>

      <p className="test-source">Source: page {result.source_page}</p>

      {explanation ? (
        <div className="test-explanation">
          {explanation.simple_explanation ? (
            <div>
              <h4>What your report shows</h4>
              <p>{explanation.simple_explanation}</p>
            </div>
          ) : null}
          {explanation.general_information ? (
            <div>
              <h4>About this test</h4>
              <p>{explanation.general_information}</p>
            </div>
          ) : null}
          {explanation.cannot_determine ? (
            <div>
              <h4>What this cannot tell you</h4>
              <p>{explanation.cannot_determine}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      {result.raw_line ? (
        <p className="test-raw">Original report text: “{result.raw_line}”</p>
      ) : null}
    </article>
  )
}
