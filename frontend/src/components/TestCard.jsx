const STATUS_CLASS = {
  normal: 'badge badge--normal',
  low: 'badge badge--low',
  high: 'badge badge--high',
  abnormal: 'badge badge--outside',
  unknown: 'badge badge--unknown',
}

export default function TestCard({ result, explanation }) {
  const valueLabel = [result.value_text, result.unit].filter(Boolean).join(' ')

  return (
    <article className="test-card">
      <header className="test-card-header">
        <h3 className="test-name">{result.test_name}</h3>
        <span className={STATUS_CLASS[result.status] ?? STATUS_CLASS.unknown}>
          {result.status_bn}
        </span>
      </header>

      <p className="test-value">{valueLabel || 'মান পাওয়া যায়নি'}</p>

      <p className="test-reference">
        স্বাভাবিক সীমা:{' '}
        {result.reference?.raw_text
          ? result.reference.raw_text
          : 'রিপোর্টে দেওয়া সীমা নেই'}
      </p>

      <p className="test-source">উৎস: পৃষ্ঠা {result.source_page}</p>

      {explanation ? (
        <div className="test-explanation">
          {explanation.simple_explanation ? (
            <div className="block">
              <h4>সহজ ব্যাখ্যা</h4>
              <p>{explanation.simple_explanation}</p>
            </div>
          ) : null}
          {explanation.general_information ? (
            <div className="block">
              <h4>সাধারণ তথ্য</h4>
              <p>{explanation.general_information}</p>
            </div>
          ) : null}
          {explanation.cannot_determine ? (
            <div className="block">
              <h4>যা নির্ধারণ করা যায়নি</h4>
              <p>{explanation.cannot_determine}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      {result.raw_line ? <p className="test-raw">রিপোর্টের লেখা: “{result.raw_line}”</p> : null}
    </article>
  )
}
