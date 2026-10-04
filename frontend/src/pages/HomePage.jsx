import { useRef, useState } from 'react'
import Disclaimer from '../components/Disclaimer.jsx'
import { uploadReport } from '../services/api.js'

const ACCEPTED = '.pdf,.jpg,.jpeg,.png'

export default function HomePage({ health, maxSizeMb, onUploaded }) {
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  async function handleFile(file) {
    if (!file) return
    setError(null)

    const lower = file.name.toLowerCase()
    if (!/\.(pdf|jpe?g|png)$/.test(lower)) {
      setError('শুধুমাত্র PDF, JPG, JPEG বা PNG ফাইল দেওয়া যাবে।')
      return
    }
    if (file.size > maxSizeMb * 1024 * 1024) {
      setError(`ফাইলের আকত অনেক বড়। সর্বোচ্চ ${maxSizeMb} MB নেওয়া যাবে।`)
      return
    }

    setBusy(true)
    try {
      const result = await uploadReport(file)
      onUploaded(result.report_id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <header className="hero">
        <h1>AI Medical Report Explainer</h1>
        <p className="tagline">আপনার মেডিকেল রিপোর্ট সহজ বাংলায় বুঝুন।</p>
      </header>

      <section className="uploader">
        <div
          className={`dropzone${dragging ? ' dropzone--active' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            handleFile(e.dataTransfer.files?.[0])
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
          }}
        >
          <p className="dropzone-title">রিপোর্ট আপলোড করুন</p>
          <p className="dropzone-hint">ফাইলটি এখানে টেনে দিন বা ক্লিক করে বেছে নিন</p>
          <p className="dropzone-meta">
            Supported: PDF, JPG, JPEG, PNG — সর্বোচ্চ {maxSizeMb} MB
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED}
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>

        {busy ? <p className="status">ফাইল আপলোড হচ্ছে…</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </section>

      <Disclaimer
        aiNotice={
          health && health.ai_configured === false
            ? 'AI ব্যাখ্যা চালু নেই। ফলাফলগুলো শুধু রিপোর্টের লেখা থেকে দেখানো হচ্ছে।'
            : null
        }
      />
    </main>
  )
}
