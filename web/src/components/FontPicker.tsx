import { useState } from 'react'
import { applyFont, FONTS, loadFontChoice } from '../lib/fonts'

export default function FontPicker() {
  const [font, setFont] = useState(loadFontChoice)

  return (
    <select
      className="font-picker"
      aria-label="Font"
      title="Font (saved on this device)"
      value={font}
      onChange={(e) => {
        applyFont(e.target.value)
        setFont(e.target.value)
      }}
    >
      {FONTS.map((f) => (
        <option key={f.id} value={f.id}>{f.label}</option>
      ))}
    </select>
  )
}
