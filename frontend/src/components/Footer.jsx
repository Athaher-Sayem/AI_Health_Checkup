export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-brand">AI Medical Report Explainer</div>

        <div className="footer-contact">
          <span>Athaher Sayem</span>
          <span className="footer-dot" aria-hidden="true" />
          <a href="mailto:athahersayemfahim@gmail.com">athahersayemfahim@gmail.com</a>
        </div>

        <p className="footer-legal">
          এই অ্যাপটি একটি শিক্ষামূলক টুল। এটি কোনো রোগ নির্ণয় বা চিকিৎসার বিকল্প নয়।
          চিকিৎসা সংক্রান্ত সিদ্ধান্তের জন্য যোগ্য চিকিৎসকের পরামর্শ নিন।
        </p>
      </div>
    </footer>
  )
}
