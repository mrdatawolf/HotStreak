/**
 * Small SVG chart kit for the Reports page.
 *
 * Follows one set of rules: thin marks (bars <= 24px, 2px lines, 4px rounded data-ends), hairline solid grid,
 * 2px surface gaps between touching fills, text in text colors (never the series color), a legend for 2+ series,
 * a hover/focus tooltip on every chart, and a table view so no value is only reachable by hovering.
 * Colors come from the --series-* / --div-* tokens in index.css (validated for colorblind safety in both themes).
 */
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

// ---------- helpers ----------

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** 0 → max in 3–5 round steps (1, 2, 2.5, 5 × 10^n). */
function niceTicks(max: number, target = 4): number[] {
  if (max <= 0) return [0, 1]
  const raw = max / target
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag
  const ticks = []
  for (let v = 0; v < max + step * 0.999; v += step) ticks.push(v)
  return ticks
}

/** Rounded data-end, square at the baseline. */
function columnPath(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

function barPath(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.min(r, h / 2, w)
  return `M${x},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h - rr}Q${x + w},${y + h} ${x + w - rr},${y + h}H${x}Z`
}

// ---------- chrome ----------

export type Series = { key: string; label: string; color: string }

export function Legend({ series, kind = 'rect' }: { series: Series[]; kind?: 'rect' | 'line' }) {
  return (
    <ul className="viz-legend">
      {series.map((s) => (
        <li key={s.key}>
          <span className={kind === 'line' ? 'key-line' : 'key-rect'} style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

type TipRow = { color?: string; label: string; value: string }
type Tip = { x: number; y: number; title: string; rows: TipRow[] } | null

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null
  return (
    <div className="viz-tooltip" style={{ left: tip.x, top: tip.y }} role="status">
      <div className="viz-tooltip-title">{tip.title}</div>
      {tip.rows.map((r) => (
        <div key={r.label} className="viz-tooltip-row">
          {r.color && <span className="key-line" style={{ background: r.color }} />}
          <strong>{r.value}</strong>
          <span>{r.label}</span>
        </div>
      ))}
    </div>
  )
}

/** Card with title, optional legend, and a Chart/Table toggle. */
export function ChartCard(props: {
  title: string
  subtitle?: ReactNode
  legend?: ReactNode
  table: { head: string[]; rows: (string | number)[][]; numeric?: boolean[] }
  wide?: boolean
  children: ReactNode
}) {
  const [showTable, setShowTable] = useState(false)
  return (
    <section className={props.wide ? 'viz-card wide' : 'viz-card'}>
      <header className="viz-card-head">
        <div>
          <h2>{props.title}</h2>
          {props.subtitle && <p className="viz-sub">{props.subtitle}</p>}
        </div>
        <button type="button" className="viz-toggle" aria-pressed={showTable} onClick={() => setShowTable(!showTable)}>
          {showTable ? 'Chart' : 'Table'}
        </button>
      </header>
      {!showTable && props.legend}
      {showTable ? (
        <div className="table-wrap viz-table">
          <table>
            <thead>
              <tr>{props.table.head.map((h, i) => <th key={h} className={props.table.numeric?.[i] ? 'num' : undefined}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {props.table.rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci} className={props.table.numeric?.[ci] ? 'num' : undefined}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : props.children}
    </section>
  )
}

// ---------- stat tile ----------

export function StatTile(props: {
  label: string
  value: string
  /** Fractional change vs the prior period; up is good unless `downIsGood`. */
  delta?: number | null
  deltaLabel?: string
  note?: string
  spark?: number[]
  hero?: boolean
}) {
  const { delta } = props
  const dir = delta == null || Math.abs(delta) < 0.0005 ? 'flat' : delta > 0 ? 'up' : 'down'
  return (
    <div className={props.hero ? 'stat hero' : 'stat'}>
      <div className="stat-label">{props.label}</div>
      <div className="stat-value">{props.value}</div>
      {delta != null && (
        <div className={`stat-delta ${dir}`}>
          <span aria-hidden="true">{dir === 'up' ? '▲' : dir === 'down' ? '▼' : '■'}</span>{' '}
          {dir === 'flat' ? 'No change' : `${Math.abs(delta * 100).toFixed(Math.abs(delta) < 0.1 ? 1 : 0)}%`}
          {props.deltaLabel && <span className="muted"> {props.deltaLabel}</span>}
        </div>
      )}
      {props.note && <div className="stat-note">{props.note}</div>}
      {props.spark && props.spark.length > 1 && <Sparkline values={props.spark} />}
    </div>
  )
}

function Sparkline({ values }: { values: number[] }) {
  const w = 120, h = 28
  const max = Math.max(...values, 1)
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 2 - (v / max) * (h - 4)])
  const last = pts[pts.length - 1]
  return (
    <svg className="sparkline" width={w} height={h} aria-hidden="true">
      <polyline points={pts.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--viz-context)" strokeWidth={2}
        strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={3} fill="var(--series-1)" />
    </svg>
  )
}

// ---------- line chart ----------

type LineSeries = Series & { values: (number | null)[] }

export function LineChart(props: {
  xLabels: string[]
  series: LineSeries[]
  format: (v: number) => string
  axisFormat?: (v: number) => string
  height?: number
  label: string
}) {
  const { xLabels, series, format } = props
  const axisFormat = props.axisFormat ?? format
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [index, setIndex] = useState<number | null>(null)
  const height = props.height ?? 260
  const m = { top: 12, right: 56, bottom: 28, left: 56 }
  const iw = Math.max(0, width - m.left - m.right)
  const ih = height - m.top - m.bottom
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null))
  const ticks = niceTicks(Math.max(...all, 0))
  const yMax = ticks[ticks.length - 1]
  const x = (i: number) => m.left + (xLabels.length === 1 ? iw / 2 : (i / (xLabels.length - 1)) * iw)
  const y = (v: number) => m.top + ih - (v / yMax) * ih
  const labelEvery = Math.ceil(xLabels.length / Math.max(1, Math.floor(iw / 56)))

  function pick(clientX: number, rect: DOMRect) {
    const px = clientX - rect.left - m.left
    setIndex(Math.max(0, Math.min(xLabels.length - 1, Math.round((px / iw) * (xLabels.length - 1)))))
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      e.stopPropagation()
      const d = e.key === 'ArrowRight' ? 1 : -1
      setIndex((i) => Math.max(0, Math.min(xLabels.length - 1, (i ?? (d > 0 ? -1 : xLabels.length)) + d)))
    }
  }

  const tip: Tip = index == null ? null : {
    x: Math.min(x(index) + 12, Math.max(0, width - 190)),
    y: m.top,
    title: xLabels[index],
    rows: series.map((s) => ({ color: s.color, label: s.label, value: s.values[index] == null ? '—' : format(s.values[index]!) })),
  }

  return (
    <div className="viz-plot" ref={wrap}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={props.label} tabIndex={0} onKeyDown={onKey}
          onFocus={() => setIndex((i) => i ?? xLabels.length - 1)} onBlur={() => setIndex(null)}
          onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setIndex(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left} x2={m.left + iw} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} />
              <text x={m.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">{axisFormat(t)}</text>
            </g>
          ))}
          {xLabels.map((l, i) => (i % labelEvery === 0 || i === xLabels.length - 1) && (
            <text key={i} x={x(i)} y={height - 8} textAnchor="middle" className="viz-tick">{l}</text>
          ))}
          {index != null && <line x1={x(index)} x2={x(index)} y1={m.top} y2={m.top + ih} stroke="var(--viz-axis)" />}
          {series.map((s) => {
            // Break the line where values are missing.
            const segs: string[] = []
            let cur = ''
            s.values.forEach((v, i) => {
              if (v == null) { if (cur) segs.push(cur); cur = ''; return }
              cur += `${cur ? 'L' : 'M'}${x(i)},${y(v)}`
            })
            if (cur) segs.push(cur)
            return segs.map((d, i) => (
              <path key={`${s.key}${i}`} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))
          })}
          {/* End label on the lead series only. */}
          {(() => {
            const s = series[0]
            const li = s.values.length - 1
            const v = s.values[li]
            return v == null ? null : (
              <g>
                <circle cx={x(li)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                <text x={x(li) + 8} y={y(v)} dy="0.32em" className="viz-label">{axisFormat(v)}</text>
              </g>
            )
          })()}
          {index != null && series.map((s) => s.values[index] != null && (
            <circle key={s.key} cx={x(index)} cy={y(s.values[index]!)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
          ))}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  )
}

// ---------- stacked columns ----------

export function StackedColumns(props: {
  xLabels: string[]
  series: LineSeries[]
  format: (v: number) => string
  axisFormat?: (v: number) => string
  height?: number
  label: string
}) {
  const { xLabels, series, format } = props
  const axisFormat = props.axisFormat ?? format
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = props.height ?? 260
  const m = { top: 12, right: 12, bottom: 28, left: 56 }
  const iw = Math.max(0, width - m.left - m.right)
  const ih = height - m.top - m.bottom
  const totals = xLabels.map((_, i) => series.reduce((s, se) => s + (se.values[i] ?? 0), 0))
  const ticks = niceTicks(Math.max(...totals, 0))
  const yMax = ticks[ticks.length - 1]
  const band = iw / xLabels.length
  const bw = Math.min(24, band * 0.7)
  const y = (v: number) => m.top + ih - (v / yMax) * ih
  const labelEvery = Math.ceil(xLabels.length / Math.max(1, Math.floor(iw / 56)))
  const GAP = 2

  const tip: Tip = hover == null ? null : {
    x: Math.min(m.left + band * hover + band / 2 + 14, Math.max(0, width - 200)),
    y: m.top,
    title: `${xLabels[hover]} · ${format(totals[hover])}`,
    rows: [...series].reverse().map((s) => ({ color: s.color, label: s.label, value: format(s.values[hover] ?? 0) })),
  }

  return (
    <div className="viz-plot" ref={wrap}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={props.label} onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left} x2={m.left + iw} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} />
              <text x={m.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">{axisFormat(t)}</text>
            </g>
          ))}
          {xLabels.map((l, i) => {
            const cx = m.left + band * i + band / 2
            let base = y(0)
            const segs = series.map((s) => {
              const v = s.values[i] ?? 0
              const h = (v / yMax) * ih
              const top = base - h
              const seg = { s, top, h, isTop: false }
              base = top
              return seg
            }).filter((seg) => seg.h > 0)
            if (segs.length) segs[segs.length - 1].isTop = true
            return (
              <g key={i} className={hover === i ? 'viz-col hover' : 'viz-col'}
                tabIndex={0} aria-label={`${l}: ${format(totals[i])}`}
                onPointerEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                {/* Hit area: the whole band, not just the painted bar. */}
                <rect x={m.left + band * i} y={m.top} width={band} height={ih} fill="transparent" />
                {segs.map(({ s, top, h, isTop }) => {
                  // 2px surface gap between stacked segments (taken off the top of each lower segment).
                  const gh = isTop ? h : Math.max(0, h - GAP)
                  const gy = isTop ? top : top + GAP
                  return isTop
                    ? <path key={s.key} d={columnPath(cx - bw / 2, gy, bw, gh)} fill={s.color} />
                    : <rect key={s.key} x={cx - bw / 2} y={gy} width={bw} height={gh} fill={s.color} />
                })}
                {(i % labelEvery === 0 || i === xLabels.length - 1) && (
                  <text x={cx} y={height - 8} textAnchor="middle" className="viz-tick">{l}</text>
                )}
              </g>
            )
          })}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  )
}

// ---------- horizontal bars ----------

export type BarRow = { key: string; label: string; detail?: string | null; value: number; display: string; note?: string }

export function BarList(props: {
  rows: BarRow[]
  color?: string
  /** Optional reference line, e.g. 1.0 for 100% of quota. */
  target?: { value: number; label: string }
  max?: number
  label: string
  /** Makes rows clickable (and Enter/Space), e.g. to filter by that row. */
  onSelect?: (row: BarRow) => void
}) {
  const { rows, target, onSelect } = props
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const color = props.color ?? 'var(--series-1)'
  const labelW = Math.min(220, Math.max(100, width * 0.4))
  const maxChars = Math.floor((labelW - 12) / 7)
  const valueW = 76
  const rowH = 30
  const bh = 16
  const m = { top: target ? 18 : 4, bottom: 4 }
  const iw = Math.max(0, width - labelW - valueW - 8)
  const max = Math.max(props.max ?? 0, ...rows.map((r) => r.value), target?.value ?? 0, 1e-9)
  const height = m.top + rows.length * rowH + m.bottom
  const x = (v: number) => labelW + (v / max) * iw
  const titleId = useId()

  const tip: Tip = hover == null ? null : {
    x: Math.min(x(rows[hover].value) + 10, Math.max(0, width - 200)),
    y: m.top + hover * rowH + rowH,
    title: rows[hover].detail ? `${rows[hover].label} · ${rows[hover].detail}` : rows[hover].label,
    rows: [{ label: rows[hover].note ?? '', value: rows[hover].display }],
  }

  return (
    <div className="viz-plot" ref={wrap}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-labelledby={titleId} onPointerLeave={() => setHover(null)}>
          <title id={titleId}>{props.label}</title>
          {target && (
            <g>
              <line x1={x(target.value)} x2={x(target.value)} y1={m.top - 4} y2={height - m.bottom} stroke="var(--viz-axis)" />
              <text x={x(target.value)} y={10} textAnchor="middle" className="viz-tick">{target.label}</text>
            </g>
          )}
          {rows.map((r, i) => {
            const cy = m.top + i * rowH + rowH / 2
            const w = Math.max(0, x(r.value) - labelW)
            return (
              <g key={r.key} className={`viz-bar${hover === i ? ' hover' : ''}${onSelect ? ' selectable' : ''}`} tabIndex={0}
                role={onSelect ? 'button' : undefined}
                aria-label={`${r.label}: ${r.display}`}
                onPointerEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
                onClick={onSelect && (() => onSelect(r))}
                onKeyDown={onSelect && ((e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(r) }
                })}>
                <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill="transparent" />
                <text x={labelW - 10} y={cy} dy="0.32em" textAnchor="end" className="viz-cat">
                  {r.label.length > maxChars ? `${r.label.slice(0, maxChars - 1)}…` : r.label}
                </text>
                {w > 0 && <path d={barPath(labelW, cy - bh / 2, w, bh)} fill={color} />}
                <text x={labelW + w + 6} y={cy} dy="0.32em" className="viz-label">{r.display}</text>
              </g>
            )
          })}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  )
}

// ---------- single-series columns ----------

export function Columns(props: { rows: BarRow[]; color?: string; height?: number; label: string }) {
  const { rows } = props
  const [wrap, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = props.height ?? 220
  const m = { top: 20, bottom: 28, left: 8, right: 8 }
  const iw = Math.max(0, width - m.left - m.right)
  const ih = height - m.top - m.bottom
  const max = Math.max(...rows.map((r) => r.value), 1e-9)
  const band = iw / rows.length
  const bw = Math.min(24, band * 0.6)
  const color = props.color ?? 'var(--series-1)'

  const tip: Tip = hover == null ? null : {
    x: Math.min(m.left + band * hover + band / 2 + 14, Math.max(0, width - 200)),
    y: m.top,
    title: rows[hover].label,
    rows: [{ label: rows[hover].note ?? '', value: rows[hover].display }],
  }

  return (
    <div className="viz-plot" ref={wrap}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={props.label} onPointerLeave={() => setHover(null)}>
          <line x1={m.left} x2={m.left + iw} y1={m.top + ih} y2={m.top + ih} stroke="var(--viz-axis)" />
          {rows.map((r, i) => {
            const cx = m.left + band * i + band / 2
            const h = (r.value / max) * ih
            return (
              <g key={r.key} className={hover === i ? 'viz-bar hover' : 'viz-bar'} tabIndex={0} aria-label={`${r.label}: ${r.display}`}
                onPointerEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                <rect x={m.left + band * i} y={m.top} width={band} height={ih} fill="transparent" />
                {h > 0 && <path d={columnPath(cx - bw / 2, m.top + ih - h, bw, h)} fill={color} />}
                <text x={cx} y={m.top + ih - h - 6} textAnchor="middle" className="viz-label">{r.display}</text>
                <text x={cx} y={height - 8} textAnchor="middle" className="viz-tick">{r.label}</text>
              </g>
            )
          })}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  )
}

// ---------- diverging heatmap (attainment) ----------

const ATTAINMENT_BINS = [
  { max: 0.5, label: 'Under 50%', fill: 'var(--div-low-2)', ink: 'var(--div-ink-strong)' },
  { max: 0.9, label: '50–89%', fill: 'var(--div-low-1)', ink: 'var(--div-ink-soft)' },
  { max: 1.1, label: '90–109%', fill: 'var(--div-mid)', ink: 'var(--div-ink-soft)' },
  { max: 1.5, label: '110–149%', fill: 'var(--div-high-1)', ink: 'var(--div-ink-soft)' },
  { max: Infinity, label: '150%+', fill: 'var(--div-high-2)', ink: 'var(--div-ink-strong)' },
]

const binFor = (v: number) => ATTAINMENT_BINS.find((b) => v < b.max)!

export function AttainmentHeatmap(props: { rows: { key: string; label: string; values: (number | null)[] }[]; cols: string[]; label: string }) {
  const { rows, cols } = props
  const [hover, setHover] = useState<string | null>(null)
  return (
    <div className="heatmap-wrap">
      <table className="heatmap" aria-label={props.label}>
        <thead>
          <tr><th />{cols.map((c) => <th key={c} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              {r.values.map((v, i) => {
                const id = `${r.key}:${i}`
                if (v == null) return <td key={i} className="empty" title={`${r.label}, ${cols[i]}: no quota`}>·</td>
                const bin = binFor(v)
                return (
                  <td key={i} tabIndex={0} className={hover === id ? 'hover' : undefined}
                    style={{ background: bin.fill, color: bin.ink }}
                    title={`${r.label}, ${cols[i]}: ${Math.round(v * 100)}% of quota`}
                    onPointerEnter={() => setHover(id)} onPointerLeave={() => setHover(null)}>
                    {Math.round(v * 100)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="viz-legend">
        {ATTAINMENT_BINS.map((b) => (
          <li key={b.label}><span className="key-rect" style={{ background: b.fill }} />{b.label}</li>
        ))}
        <li><span className="muted">· = no quota</span></li>
      </ul>
    </div>
  )
}
