import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion, type Variants } from 'framer-motion'
import { AlertTriangle, CheckCircle2, Info, Sparkles, X } from 'lucide-react'
import type { Component, FieldStatus } from './types'

// ---------- 書式 ----------

export const yen = (n: number | null | undefined) =>
  n == null ? '—' : `${n < 0 ? '−' : ''}¥${Math.abs(Math.round(n)).toLocaleString('ja-JP')}`
export const num = (n: number | null | undefined, d = 0) =>
  n == null ? '—' : n.toLocaleString('ja-JP', { maximumFractionDigits: d, minimumFractionDigits: 0 })
export const pct = (n: number | null | undefined, d = 1) => (n == null ? '—' : `${(n * 100).toFixed(d)}%`)
export function dt(s?: string | null) {
  if (!s) return '—'
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
export function dateOnly(s?: string | null) {
  if (!s) return '—'
  return s.slice(0, 10).replace(/-/g, '/')
}
export const initials = (name: string) => name.replace(/\s/g, '').slice(0, 1)
const WEEK = ['日', '月', '火', '水', '木', '金', '土']
/** 2026-10-30 → 令和8年10月30日（金） */
export function wareki(d = new Date()) {
  const y = d.getFullYear() - 2018
  return `令和${y === 1 ? '元' : y}年${d.getMonth() + 1}月${d.getDate()}日（${WEEK[d.getDay()]}）`
}

/** 提出期限までの日数（当日 0・超過は負） */
export function dueInfo(due?: string | null) {
  if (!due) return null
  const d = new Date(`${due.slice(0, 10)}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const n = Math.round((d.getTime() - today.getTime()) / 86400000)
  if (Number.isNaN(n)) return null
  const label = n < 0 ? `${-n}日超過` : n === 0 ? '本日締切' : `あと${n}日`
  return { n, label, tone: n <= 2 ? 'hot' : n <= 7 ? 'near' : 'calm' }
}

/** 日付（YYYY-MM-DD）を「2026年11月14日（土）」の形にする */
export function jaDate(iso: string) {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日（${WEEK[d.getDay()]}）`
}

// ---------- 動きの共通定義 ----------

export const stagger: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.055, delayChildren: 0.04 } } }
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 260, damping: 24 } },
}
export const pop: Variants = {
  hidden: { opacity: 0, scale: 0.92 },
  show: { opacity: 1, scale: 1, transition: { type: 'spring', stiffness: 300, damping: 22 } },
}

/** 数値を 0 から目標値までカウントアップ表示する。 */
export function CountUp({ value, format = (n) => num(n), duration = 1.1 }: { value: number; format?: (n: number) => string; duration?: number }) {
  const reduce = useReducedMotion()
  const [shown, setShown] = useState(reduce ? value : 0)
  const from = useRef(0)
  useEffect(() => {
    if (reduce) { setShown(value); return }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / (duration * 1000))
      const e = 1 - Math.pow(1 - k, 3)
      setShown(a + (value - a) * e)
      if (k < 1) raf = requestAnimationFrame(tick)
      else from.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration, reduce])
  return <span className="num">{format(Math.round(shown))}</span>
}

// ---------- トースト ----------

type Toast = { id: number; kind: 'info' | 'success' | 'error'; text: string }
const ToastCtx = createContext<(text: string, kind?: Toast['kind']) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((text: string, kind: Toast['kind'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t.slice(-3), { id, kind, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <motion.div key={t.id} layout className={`toast ${t.kind}`} role="status"
              initial={{ opacity: 0, x: 60, scale: 0.9 }} animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0, x: 60, scale: 0.9 }}
              transition={{ type: 'spring', stiffness: 380, damping: 28 }}>
              {t.kind === 'error' ? <AlertTriangle size={17} /> : t.kind === 'success' ? <CheckCircle2 size={17} /> : <Info size={17} />}
              <span className="grow">{t.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  )
}
export const useToast = () => useContext(ToastCtx)

// ---------- モーダル ----------

export function Modal({ title, onClose, children, footer, width, className, head, label }: {
  title?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number; className?: string
  /** 見出し部分を丸ごと差し替える場合（閉じるボタンも自前で置く） */
  head?: ReactNode; label?: string
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <motion.div className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <motion.div className={`modal ${className ?? ''}`} style={width ? { width } : undefined} role="dialog" aria-modal="true" aria-label={label}
        initial={{ opacity: 0, y: 24, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: 'spring', stiffness: 320, damping: 26 }}>
        {head ?? (
          <div className="modal-head row">
            <h3 className="grow">{title}</h3>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose} aria-label="閉じる"><X size={16} /></button>
          </div>
        )}
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </motion.div>
    </motion.div>
  )
}

// ---------- セグメントタブ（選択中の背景が滑って移動する） ----------

export function SegTabs<T extends string>({ items, value, onChange, id }: {
  items: { id: T; label: ReactNode; n?: number; tone?: 'red' | 'ai' }[]; value: T; onChange: (v: T) => void; id: string
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={`tab ${value === t.id ? 'active' : ''}`} onClick={() => onChange(t.id)}>
          {value === t.id && <motion.span layoutId={`seg-${id}`} className="tab-active-bg" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />}
          {t.label}
          {t.n != null && <span className={`n ${t.tone || ''}`}>{t.n}</span>}
        </button>
      ))}
    </div>
  )
}

// ---------- ステータス表示 ----------

export const FIELD_STATUS: Record<FieldStatus, { label: string; cls: string }> = {
  ok: { label: '抽出済', cls: 'badge-gray' },
  confirmed: { label: '確定', cls: 'badge-green' },
  edited: { label: '修正済', cls: 'badge-green' },
  resolved: { label: '解決済', cls: 'badge-green' },
  changed: { label: '変更反映', cls: 'badge-blue' },
  review: { label: '要確認', cls: 'badge-amber' },
  inferred: { label: '推定', cls: 'badge-amber' },
  conflict: { label: '矛盾', cls: 'badge-red' },
  missing: { label: '記載なし', cls: 'badge-red' },
  asked: { label: '質疑中', cls: 'badge-purple' },
  empty: { label: '記載なし', cls: 'badge-gray' },
}

export const COMP_STATUS: Record<Component['status'], { label: string; cls: string }> = {
  ok: { label: '照合済', cls: 'badge-gray' },
  confirmed: { label: '確定', cls: 'badge-green' },
  review: { label: '要確認', cls: 'badge-amber' },
  no_master: { label: 'マスタ未登録', cls: 'badge-red' },
  changed: { label: '変更反映', cls: 'badge-blue' },
  added: { label: '追加', cls: 'badge-teal' },
  deleted: { label: '削除', cls: 'badge-gray' },
  recommended: { label: '推奨追加', cls: 'badge-purple' },
  ai: { label: 'AI検出', cls: 'badge-ai' },
}

export const PROJECT_STATUS: Record<string, string> = {
  資料待ち: 'badge-gray', 解析待ち: 'badge-blue', 確認中: 'badge-amber', 確認完了: 'badge-teal', 承認待ち: 'badge-purple', 差戻し: 'badge-red',
  承認済: 'badge-green', 出力済: 'badge-solid-green',
}

export const VERDICT: Record<string, { label: string; cls: string }> = {
  ok: { label: '収容可', cls: 'badge-green' },
  ng: { label: '収容不可', cls: 'badge-red' },
  insufficient: { label: '情報不足', cls: 'badge-amber' },
}

export function Badge({ cls, children, title }: { cls: string; children: ReactNode; title?: string }) {
  return <span className={`badge ${cls}`} title={title}>{children}</span>
}

/** 抽出方法の表示（ルール／AI／両方一致）。 */
export function Methods({ methods }: { methods: string[] }) {
  if (!methods.length) return null
  const both = methods.includes('rule+ai')
  const ai = methods.some((m) => m === 'ai' || m === 'ai-support')
  const rule = methods.includes('rule')
  if (both) return <span className="method both" title="ルール抽出と AI 読解が独立に同じ値を読み取りました">ルール×AI 一致</span>
  return (
    <>
      {rule && <span className="method rule" title="辞書・ルールによる抽出">ルール</span>}
      {ai && <span className="method ai" title="AI 読解（引用が原文に存在することを照合済み）"><Sparkles size={9} />AI</span>}
    </>
  )
}

export function Confidence({ value }: { value: number }) {
  const n = value >= 0.95 ? 4 : value >= 0.85 ? 3 : value >= 0.7 ? 2 : value > 0 ? 1 : 0
  const color = n >= 4 ? 'var(--ok)' : n === 3 ? '#4fb48a' : n === 2 ? 'var(--warn)' : 'var(--danger)'
  return (
    <span className="conf" title={`信頼度 ${Math.round(value * 100)}%`}>
      {[0, 1, 2, 3].map((i) => <i key={i} style={i < n ? { background: color } : undefined} />)}
    </span>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} />
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <motion.div className="empty" initial="hidden" animate="show" variants={stagger}>
      <motion.div className="empty-icon" variants={pop}>{icon}</motion.div>
      <motion.h3 variants={fadeUp}>{title}</motion.h3>
      <motion.div variants={fadeUp}>{children}</motion.div>
    </motion.div>
  )
}

export function Progress({ value, limit, color }: { value: number; limit?: number; color?: string }) {
  const v = Math.max(0, Math.min(1.25, value))
  return (
    <div className="progress">
      <motion.div className="progress-bar" initial={{ width: 0 }} animate={{ width: `${Math.min(100, (v / 1.25) * 100)}%` }}
        transition={{ duration: 1.1, ease: [0.2, 0.8, 0.2, 1] }} style={{ background: color || 'var(--grad-ai)' }} />
      {limit != null && <div className="progress-limit" style={{ left: `${(limit / 1.25) * 100}%` }} title={`上限 ${pct(limit, 0)}`} />}
    </div>
  )
}

// ---------- 判子（データ印）・桜吹雪 ----------

/** 日付入りの丸い判子（データ印）。上段・日付・名前の三段構成。 */
export function DateStamp({ top, date, name, size = 120, color = '#d63a2b' }: { top: string; date: string; name: string; size?: number; color?: string }) {
  const fid = useId().replace(/:/g, '')
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-label={`${top} ${date} ${name}`} role="img">
      <defs>
        <filter id={`ink${fid}`}>
          <feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.4" />
        </filter>
      </defs>
      <g filter={`url(#ink${fid})`} fill={color} stroke={color} opacity="0.92">
        <circle cx="50" cy="50" r="46" fill="none" strokeWidth="4.5" />
        <line x1="10" y1="37" x2="90" y2="37" strokeWidth="2.2" />
        <line x1="10" y1="63" x2="90" y2="63" strokeWidth="2.2" />
        <text x="50" y="30" textAnchor="middle" fontSize="15" fontWeight="800" stroke="none" fontFamily="'Shippori Mincho', serif">{top}</text>
        <text x="50" y="55.5" textAnchor="middle" fontSize="13" fontWeight="700" stroke="none" fontFamily="'Zen Kaku Gothic New', sans-serif">{date}</text>
        <text x="50" y="82" textAnchor="middle" fontSize="15" fontWeight="800" stroke="none" fontFamily="'Shippori Mincho', serif">{name}</text>
      </g>
    </svg>
  )
}

/** 一文字〜二文字の角印風の判子（判定結果などに使う）。 */
export function Hanko({ text, size = 92, color = '#d63a2b', round = true }: { text: string; size?: number; color?: string; round?: boolean }) {
  const fid = useId().replace(/:/g, '')
  const fs = text.length === 1 ? 52 : text.length === 2 ? 34 : 26
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={text}>
      <defs>
        <filter id={`hk${fid}`}>
          <feTurbulence type="fractalNoise" baseFrequency="1.2" numOctaves="2" seed="3" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.6" />
        </filter>
      </defs>
      <g filter={`url(#hk${fid})`} opacity="0.93">
        {round ? <circle cx="50" cy="50" r="45" fill="none" stroke={color} strokeWidth="6" />
          : <rect x="6" y="6" width="88" height="88" rx="10" fill="none" stroke={color} strokeWidth="6" />}
        <text x="50" y="50" textAnchor="middle" dominantBaseline="central" fontSize={fs} fontWeight="800" fill={color}
          fontFamily="'Shippori Mincho', serif" letterSpacing={text.length > 1 ? 2 : 0}>{text}</text>
      </g>
    </svg>
  )
}

function Petal({ i }: { i: number }) {
  const p = useMemo(() => ({
    left: Math.random() * 100,
    size: 12 + Math.random() * 14,
    delay: Math.random() * 0.9 + (i % 5) * 0.08,
    dur: 3.2 + Math.random() * 2.6,
    sway: 40 + Math.random() * 90,
    rot: Math.random() * 360,
    hue: Math.random() > 0.5 ? ['#ffd1e0', '#f48bb0'] : ['#ffe3ec', '#f7a8c4'],
  }), [i])
  return (
    <motion.div className="petal" style={{ left: `${p.left}vw` }}
      initial={{ y: -40, x: 0, rotate: p.rot, opacity: 0 }}
      animate={{ y: '105vh', x: [0, p.sway, -p.sway / 2, p.sway / 3], rotate: p.rot + 540, opacity: [0, 1, 1, 0.9, 0] }}
      transition={{ duration: p.dur, delay: p.delay, ease: 'easeIn' }}>
      <svg width={p.size} height={p.size} viewBox="0 0 24 24">
        <defs><linearGradient id={`pg${i}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={p.hue[0]} /><stop offset="1" stopColor={p.hue[1]} /></linearGradient></defs>
        <path d="M12 1 C 19 6 22 14 12 23 C 2 14 5 6 12 1 Z M12 1 l -2 4 l 2 -1.4 l 2 1.4 z" fill={`url(#pg${i})`} />
      </svg>
    </motion.div>
  )
}

/** 桜吹雪。count 枚の花びらを一度だけ降らせる。 */
export function Sakura({ count = 42 }: { count?: number }) {
  const reduce = useReducedMotion()
  if (reduce) return null
  return <>{Array.from({ length: count }, (_, i) => <Petal key={i} i={i} />)}</>
}

/** 画面中央に判子を「ドン」と押す演出。判子が消えた後も桜は降り続け、onDone で閉じる。 */
export function StampOverlay({ children, onDone, petals = true }: { children: ReactNode; onDone: () => void; petals?: boolean }) {
  useEffect(() => {
    const t = setTimeout(onDone, petals ? 6200 : 2800)
    return () => clearTimeout(t)
  }, [onDone, petals])
  return (
    <>
      <motion.div className="stamp-stage" initial={{ opacity: 1 }} animate={{ opacity: [1, 1, 0] }} transition={{ duration: 2.8, times: [0, 0.8, 1] }}>
        <motion.div className="stamp-dim" initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 1, 0] }} transition={{ duration: 2.8, times: [0, 0.12, 0.8, 1] }} />
        <motion.div className="stamp-flash" initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 0] }} transition={{ duration: 0.9, delay: 0.32 }} />
        <motion.div initial={{ scale: 3.2, rotate: -32, opacity: 0, filter: 'blur(6px)' }}
          animate={{ scale: [3.2, 0.9, 1.06, 1], rotate: [-32, -10, -13, -12], opacity: 1, filter: 'blur(0px)' }}
          transition={{ duration: 0.62, times: [0, 0.55, 0.8, 1], ease: 'easeOut' }}>
          {children}
        </motion.div>
      </motion.div>
      {petals && <Sakura count={56} />}
    </>
  )
}
