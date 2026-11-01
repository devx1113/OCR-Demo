import { useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, Building2, CalendarClock, Check, FolderKanban, Sparkles, X } from 'lucide-react'
import { api } from '../api'
import { navigate } from '../App'
import type { ProjectSummary } from '../types'
import { Modal, Spinner, dueInfo, fadeUp, jaDate, stagger, useToast } from '../ui'

const FLOW = ['案件情報', '資料の登録', 'AI 解析・確認']

/** 今日から n 日後（または n か月後）を YYYY-MM-DD で返す（ローカル日付） */
function later(days: number, months = 0) {
  const d = new Date()
  d.setMonth(d.getMonth() + months)
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const QUICK = [
  { label: '1週間後', value: () => later(7) },
  { label: '2週間後', value: () => later(14) },
  { label: '1か月後', value: () => later(0, 1) },
]

/** 既存案件から次の見積番号を予測する（採番はサーバー側で行う） */
function nextQuoteNo(items: ProjectSummary[]) {
  const year = new Date().getFullYear()
  const nums = items.map((p) => p.quote_no).filter((q) => q?.startsWith(`Q${year}-`)).map((q) => Number(q.split('-')[1]) || 0)
  return `Q${year}-${String((nums.length ? Math.max(...nums) : 0) + 1).padStart(4, '0')}`
}

export default function NewProjectDialog({ items, onClose }: { items: ProjectSummary[]; onClose: () => void }) {
  const toast = useToast()
  const [form, setForm] = useState({ name: '', customer: '', due_date: '' })
  const [busy, setBusy] = useState(false)
  const dateRef = useRef<HTMLInputElement>(null)
  const quoteNo = useMemo(() => nextQuoteNo(items), [items])
  const customers = useMemo(() => [...new Set(items.map((p) => p.customer).filter(Boolean))], [items])
  const due = dueInfo(form.due_date)
  const ready = form.name.trim().length > 0

  const create = async () => {
    if (!ready || busy) return
    setBusy(true)
    try {
      const p = await api.createProject({ ...form, due_date: form.due_date || undefined })
      navigate(`/projects/${p.id}/documents`)
    } catch (e) {
      toast((e as Error).message, 'error')
      setBusy(false)
    }
  }
  const openPicker = () => {
    const el = dateRef.current
    if (!el) return
    try { el.showPicker() } catch { el.focus() }
  }

  return (
    <Modal className="np-modal" label="新規案件" onClose={onClose} head={
      <div className="np-hero">
        <div className="np-hero-bg" aria-hidden><span className="a1" /><span className="a2" /></div>
        <motion.div className="np-seal" initial={{ scale: 1.8, rotate: -20, opacity: 0 }} animate={{ scale: 1, rotate: 0, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 300, damping: 15, delay: 0.1 }}>
          <span className="np-seal-ring" aria-hidden />新
        </motion.div>
        <div className="grow">
          <div className="np-eyebrow"><span className="hishi sm" />NEW ESTIMATE</div>
          <div className="np-title">新規案件</div>
          <div className="np-sub">仕様書を登録すると、AI が読み解いて見積までを支援します</div>
        </div>
        <div className="np-qno" title="作成時に採番されます">
          <small>見積番号（予定）</small><b>{quoteNo}</b>
        </div>
        <button className="np-close" onClick={onClose} aria-label="閉じる"><X size={16} /></button>
      </div>
    } footer={
      <>
        <span className="np-hint">{ready ? <><Check size={13} />作成後、資料の登録画面に進みます</> : '案件名を入力してください'}</span>
        <span className="spacer" />
        <button className="btn" onClick={onClose}>キャンセル</button>
        <button className={`btn btn-primary np-submit ${ready ? 'ready' : ''}`} onClick={create} disabled={!ready || busy}>
          {busy ? <><Spinner size={14} />作成中…</> : <>作成して資料を登録<ArrowRight size={15} /></>}
        </button>
      </>
    }>
      <div className="np-flow" aria-label="この後の流れ">
        {FLOW.map((f, i) => (
          <motion.div key={f} className={`np-flow-step ${i === 0 ? 'now' : ''}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.08 }}>
            <span className="np-flow-no">{i + 1}</span>{f}
            {i < FLOW.length - 1 && <span className="np-flow-line" aria-hidden />}
          </motion.div>
        ))}
      </div>

      <motion.form className="np-form" variants={stagger} initial="hidden" animate="show" onSubmit={(e) => { e.preventDefault(); create() }}>
        <motion.label variants={fadeUp} className="np-field">
          <span className="np-label">案件名<em>必須</em><span className="spacer" /><span className="np-count">{form.name.length} / 200</span></span>
          <span className="np-input-wrap">
            <span className="np-ic"><FolderKanban size={16} /></span>
            <input className="input np-input" autoFocus maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例：〇〇工場 動力制御盤" />
            {ready && <motion.span className="np-ok" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 18 }}><Check size={12} strokeWidth={3} /></motion.span>}
          </span>
        </motion.label>

        <motion.label variants={fadeUp} className="np-field">
          <span className="np-label">顧客名<span className="np-opt">任意</span></span>
          <span className="np-input-wrap">
            <span className="np-ic"><Building2 size={16} /></span>
            <input className="input np-input" list="np-customers" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}
              placeholder="例：〇〇設備株式会社" />
            <datalist id="np-customers">{customers.map((c) => <option key={c} value={c} />)}</datalist>
          </span>
        </motion.label>

        <motion.div variants={fadeUp} className="np-field">
          <span className="np-label">見積提出期限<span className="np-opt">任意</span></span>
          <div className="np-input-wrap">
            <span className="np-ic"><CalendarClock size={16} /></span>
            <button type="button" className={`input np-input np-date ${form.due_date ? 'set' : ''}`} onClick={openPicker} aria-label="見積提出期限を選択">
              {form.due_date ? jaDate(form.due_date) : <span className="np-ph">日付を選択</span>}
            </button>
            <input ref={dateRef} type="date" className="np-date-native" tabIndex={-1} aria-hidden value={form.due_date}
              onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
            <AnimatePresence>
              {due && (
                <motion.span key={due.label} className={`np-due ${due.tone}`} initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 20 }}>{due.label}</motion.span>
              )}
            </AnimatePresence>
          </div>
          <div className="np-quick">
            {QUICK.map((q) => {
              const v = q.value()
              return <button key={q.label} type="button" className={`np-pill ${form.due_date === v ? 'on' : ''}`} onClick={() => setForm({ ...form, due_date: v })}>{q.label}</button>
            })}
            {form.due_date && <button type="button" className="np-pill clear" onClick={() => setForm({ ...form, due_date: '' })}><X size={11} />クリア</button>}
          </div>
        </motion.div>
        <button type="submit" hidden />
      </motion.form>

      <motion.div className={`np-preview ${ready ? 'live' : ''}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
        <div className="np-stub"><small>見積番号</small><b>{quoteNo}</b><span className="np-stub-st">確認中</span></div>
        <div className="np-ticket">
          <div className="np-ticket-tag"><Sparkles size={11} />一覧での表示イメージ</div>
          <div className={`np-ticket-name ${form.name ? '' : 'ph'}`}>{form.name || '案件名'}</div>
          <div className="np-ticket-meta">
            <span><Building2 size={11} />{form.customer || '顧客名 未入力'}</span>
            <span><CalendarClock size={11} />{form.due_date ? jaDate(form.due_date) : '期限 未設定'}</span>
          </div>
        </div>
      </motion.div>
    </Modal>
  )
}
