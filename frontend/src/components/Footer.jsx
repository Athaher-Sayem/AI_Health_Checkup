export default function Footer() {
  return (
    <footer style={{
      marginTop: 'var(--space-12)',
      padding: 'var(--space-6)',
      borderTop: '1px solid var(--border)',
      color: 'var(--text-muted)',
      fontSize: 'var(--fs-12)',
      textAlign: 'center',
    }}>
      <div style={{ marginBottom: 'var(--space-2)' }}>
        © {new Date().getFullYear()} AI Medical Report Explainer
      </div>
      <div>
        Athaher Sayem · <a href="mailto:athahersayemfahim@gmail.com">athahersayemfahim@gmail.com</a>
      </div>
      <div style={{ marginTop: 'var(--space-2)' }}>
        Not a medical device. Consult a qualified clinician.
      </div>
    </footer>
  )
}