export default function Disclaimer({ aiNotice }) {
  return (
    <aside className="disclaimer">
      <p className="disclaimer-text">
        এই অ্যাপটি শুধুমাত্র মেডিকেল রিপোর্টের তথ্য সহজ ভাষায় বোঝাতে সাহায্য করে।
        এটি কোনো রোগ নির্ণয় বা চিকিৎসার বিকল্প নয়।
        চিকিৎসা সংক্রান্ত সিদ্ধান্তের জন্য যোগ্য চিকিৎসকের পরামর্শ নিন।
      </p>
      {aiNotice ? <p className="disclaimer-note">{aiNotice}</p> : null}
    </aside>
  )
}
