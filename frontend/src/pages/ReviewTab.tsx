import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, type Variants } from 'framer-motion'
import {
  AlertOctagon, ArrowRight, Boxes, Bot, Building2, Cable, CalendarX2, Check, ClipboardList, CornerDownRight, DoorOpen, Eraser, Eye, FileSearch,
  FileWarning, GitCompareArrows, Info, LayoutPanelTop, ScanLine, ScrollText,
  ListChecks, MessageCircleQuestion, PackageX, Pencil, Plus, ReceiptJapaneseYen, RotateCcw, SearchX, Send, ShieldAlert, ShieldCheck, Sparkles,
  Thermometer, Trash2, Undo2, type LucideIcon,
} from 'lucide-react'
import { api } from '../api'
import { useAi } from '../App'
import type { Analysis, ChatMessage, Component, Doc, Field, Issue, Source } from '../types'
import { Badge, COMP_STATUS, Confidence, CountUp, FIELD_STATUS, Methods, Modal, SegTabs, dt, fadeUp, stagger, useToast, yen } from '../ui'
import { SourceViewer } from '../viewer'
import type { Ctx } from './ProjectPage'

type Sel = { kind: 'field' | 'component' | 'risk' | 'instruction' | 'note' | 'chat'; key: string } | null
type PanelTab = 'issues' | 'panel' | 'components' | 'conditions' | 'risks' | 'chat'

const MOUNT_JA: Record<string, string> = { plate: '取付板', terminal: '端子', door: '扉面' }
const MOUNT_ICON: Record<string, React.ReactNode> = { plate: <LayoutPanelTop size={11} />, terminal: <Cable size={11} />, door: <DoorOpen size={11} /> }
const SUGGESTIONS = ['主回路電源の周波数は結局どちらが正しい？', '立会検査は何回で、見積にどう影響する？', '変更連絡書で何が変わった？', '保護等級について記載はある？']

function useDocLabel(docs: Doc[]) {
  return useMemo(() => {
    const m: Record<string, string> = {}
    const n: Record<string, number> = {}
    const base: Record<string, string> = { main: '主仕様書', supplement: '補足資料', drawing: '図面', other: '資料' }
    for (const d of docs) {
      n[d.role] = (n[d.role] || 0) + 1
      m[d.id] = base[d.role] + (docs.filter((x) => x.role === d.role).length > 1 ? n[d.role] : '')
    }
    return (id: string) => m[id] || '資料'
  }, [docs])
}

function SourceChips({ sources, label, onPick, active }: {
  sources: Source[]; label: (id: string) => string; onPick: (s: Source) => void; active: Source | null
}) {
  const uniq = sources.filter((s, i) => sources.findIndex((x) => x.doc_id === s.doc_id && x.ids.join() === s.ids.join()) === i)
  return (
    <span className="row-wrap gap-4">
      {uniq.slice(0, 3).map((s, i) => (
        <span key={i} className={`chip ${active === s ? 'active' : ''}`} title={s.text}
          onClick={(e) => { e.stopPropagation(); onPick(s) }}>
          <FileSearch size={11} />{label(s.doc_id)}{s.page ? ` p.${s.page}` : ''}
        </span>
      ))}
      {uniq.length > 3 && <span className="xs muted">+{uniq.length - 3}</span>}
    </span>
  )
}

/** マウス位置を CSS 変数に渡し、行の上で光が追従するようにする */
const spot = (e: React.MouseEvent<HTMLElement>) => {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
  e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
}

function FieldRow({ f, selected, onSelect, ctx, label, onPick, focusSrc }: {
  f: Field; selected: boolean; onSelect: () => void; ctx: Ctx; label: (id: string) => string
  onPick: (s: Source, related?: Source[]) => void; focusSrc: Source | null
}) {
  const { project, act } = ctx
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(f.value)
  const [reason, setReason] = useState('')
  useEffect(() => { setVal(f.value); setEditing(false) }, [f.value, selected])
  const st = FIELD_STATUS[f.status]
  const settled = ['confirmed', 'edited', 'resolved'].includes(f.status)
  const save = async () => {
    if (await act(() => api.fieldAction(project.id, f.key, { action: 'edit', value: val, reason }), `${f.label}を修正しました`)) setEditing(false)
  }
  return (
    <motion.div variants={fadeUp} className={`frow rv-frow st-${f.status} ${selected ? 'focused' : ''}`} onClick={onSelect} onMouseMove={spot} data-field={f.key}>
      <div className="frow-top">
        <span className="frow-label">{f.label}{f.required && <span style={{ color: 'var(--danger)' }}> *</span>}</span>
        <Badge cls={st.cls}>{st.label}</Badge>
        <Methods methods={f.methods || []} />
        <span className="spacer" />
        {f.sources.length > 0 && <Confidence value={f.confidence} />}
        <SourceChips sources={f.sources} label={label} active={focusSrc} onPick={(s) => onPick(s, f.sources)} />
      </div>
      <div className={`frow-value ${f.value ? '' : 'empty'}`}>{f.value || (f.status === 'empty' ? <span className="muted" style={{ fontWeight: 400 }}>記載なし（任意項目）</span> : '仕様書に記載がありません')}</div>
      {f.note && f.status !== 'ok' && <div className="frow-note"><Info size={12} style={{ marginTop: 2, flexShrink: 0 }} />{f.note}</div>}
      {f.change && (
        <div className="change-box">
          <div className="row gap-4"><CornerDownRight size={12} /><b>変更連絡を反映：</b>{f.change.desc}</div>
          {f.change.reason && <div className="xs" style={{ marginLeft: 16 }}>理由：{f.change.reason}{!f.change.before_matches && ' ／ ⚠ 変更前の値が現在値と一致しません'}</div>}
        </div>
      )}
      {f.key === 'outer_dims' && (project.analysis?.drawings || []).map((g) => (
        <div key={g.doc_id} className={`drawing-box ${g.mismatch.length ? 'bad' : ''}`}>
          <div className="row gap-4"><ScanLine size={12} /><b>図面（AI-OCR）との照合：</b>{g.doc_name}{g.drawing_no ? `・図番 ${g.drawing_no}` : ''}</div>
          <div className="row-wrap gap-4 mt-4">
            {g.items.map((i) => (
              <span key={i.axis} className={`drawing-ax ${i.match ? 'ok' : 'bad'}`} title={i.match ? '仕様と一致' : `仕様 ${i.spec}mm`}
                onClick={(e) => { e.stopPropagation(); onPick(i.source, g.items.map((x) => x.source)) }}>
                {i.label} {i.drawing}{i.match ? <Check size={11} /> : <> ≠ {i.spec}</>}
              </span>
            ))}
          </div>
          {g.mismatch.some((m) => m.matches_before) && <div className="xs mt-4">図面は変更連絡の「変更前」の寸法と一致しています。旧版の図面の可能性があるため、質疑書で最新図面の提示を依頼します。</div>}
        </div>
      ))}
      {(f.ai_alt || []).length > 0 && (
        <div className="ai-box row" style={{ alignItems: 'flex-start' }}>
          <Sparkles size={12} style={{ marginTop: 3, flexShrink: 0 }} />
          <div className="grow">AI 参考：{f.ai_alt.map((x) => `「${x.value}」`).join('、')}</div>
          <SourceChips sources={f.ai_alt.map((x) => x.source)} label={label} active={focusSrc} onPick={(s) => onPick(s, f.sources)} />
        </div>
      )}
      {f.candidates.length > 1 && (selected || f.status === 'conflict') && (
        <div className="col gap-4 mt-8">
          {f.candidates.map((c, i) => {
            const picked = (f.provisional ?? -1) === i
            return (
              <div key={i} className={`cand ${picked ? 'picked' : ''}`}>
                <div className="grow">
                  <div className="bold head">{c.value}</div>
                  <div className="xs muted row-wrap gap-4"><span>{c.doc_name}（受領 {c.doc_date || '—'}）{picked && f.status === 'conflict' && ' ・ 仮採用中'}</span><Methods methods={c.methods || []} /></div>
                </div>
                <SourceChips sources={c.sources} label={label} active={focusSrc} onPick={(s) => onPick(s, f.sources)} />
                <button className={`btn btn-xs ${picked && f.status === 'resolved' ? 'btn-ok' : 'btn-soft'}`}
                  onClick={(e) => { e.stopPropagation(); act(() => api.fieldAction(project.id, f.key, { action: 'choose', choice: i }), `「${c.value}」を採用しました`) }}>
                  {picked && f.status === 'resolved' ? <><Check size={12} />採用済</> : '採用'}
                </button>
              </div>
            )
          })}
        </div>
      )}
      {selected && editing && (
        <div className="col gap-8 mt-8" onClick={(e) => e.stopPropagation()}>
          {f.options ? (
            <select className="select" value={val} onChange={(e) => setVal(e.target.value)} autoFocus aria-label={`${f.label}の値`}>
              <option value="">選択してください</option>
              {f.options.map((o) => <option key={o}>{o}</option>)}
            </select>
          ) : (
            <input className="input" value={val} autoFocus aria-label={`${f.label}の値`} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && save()}
              placeholder={f.type === 'dims' ? '例：W800 × H2000 × D600 mm' : ''} />
          )}
          <input className="input input-sm" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="修正理由（任意・履歴に記録されます）" />
          <div className="row">
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!val.trim()}><Check size={13} />保存</button>
            <button className="btn btn-sm" onClick={() => setEditing(false)}>キャンセル</button>
          </div>
        </div>
      )}
      {selected && !editing && (
        <div className="frow-actions" onClick={(e) => e.stopPropagation()}>
          {!settled && f.status !== 'missing' && f.status !== 'conflict' && f.status !== 'empty' && (
            <button className="btn btn-xs btn-ok" onClick={() => act(() => api.fieldAction(project.id, f.key, { action: 'confirm' }), `${f.label}を確定しました`)}><Check size={12} />この値で確定</button>
          )}
          <button className="btn btn-xs" onClick={() => setEditing(true)}><Pencil size={12} />{f.value ? '修正' : '値を入力'}</button>
          {['conflict', 'missing', 'review', 'inferred'].includes(f.status) && (
            <button className="btn btn-xs" onClick={() => act(() => api.fieldAction(project.id, f.key, { action: 'ask' }), '質疑書に追加しました')}><MessageCircleQuestion size={12} />質疑書で確認</button>
          )}
          {f.override && (
            <button className="btn btn-xs btn-ghost" onClick={() => act(() => api.fieldReset(project.id, f.key), '自動抽出の値に戻しました')}><Undo2 size={12} />自動抽出に戻す</button>
          )}
        </div>
      )}
      {selected && f.override && (
        <div className="xs muted mt-8">{f.override.by} が {dt(f.override.at)} に操作{f.original ? `（元の値：${f.original}）` : ''}{f.override.reason ? `・理由：${f.override.reason}` : ''}</div>
      )}
    </motion.div>
  )
}

function ComponentDetail({ c, ctx, label, onPick, focusSrc }: { c: Component; ctx: Ctx; label: (id: string) => string; onPick: (s: Source, r?: Source[]) => void; focusSrc: Source | null }) {
  const { project, act } = ctx
  const [qty, setQty] = useState(String(c.qty ?? ''))
  const [model, setModel] = useState(c.model)
  useEffect(() => { setQty(String(c.qty ?? '')); setModel(c.model) }, [c.qty, c.model])
  const dirty = qty !== String(c.qty ?? '') || model !== c.model
  const save = () => {
    const body: Record<string, unknown> = {}
    if (qty !== String(c.qty ?? '')) body.qty = Number(qty)
    if (model !== c.model) body.model = model
    act(() => api.componentAction(project.id, c.key, body), `${c.name}を修正しました`)
  }
  const isRec = c.origin === 'recommended'
  return (
    <motion.div style={{ padding: '4px 4px 10px' }} onClick={(e) => e.stopPropagation()} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}>
      {c.notes.length > 0 && (
        <div className="col gap-4 mb-8">{c.notes.map((n) => <div key={n} className="frow-note"><Info size={12} style={{ marginTop: 2 }} />{n}</div>)}</div>
      )}
      {c.changes.map((ch, i) => (
        <div key={i} className="change-box">
          <div className="row gap-4"><CornerDownRight size={12} /><b>{ch.attr}を変更：</b>{String(ch.from)} <ArrowRight size={11} /> {String(ch.to)}
            <span className="spacer" /><SourceChips sources={[ch.source]} label={label} active={focusSrc} onPick={(s) => onPick(s, c.sources)} />
          </div>
          <div className="xs" style={{ marginLeft: 16 }}>理由：{ch.reason || '—'}{!ch.before_matches && ' ／ ⚠ 変更前の値が仕様書と一致しません'}</div>
        </div>
      ))}
      {c.ai_verified && <div className="ai-box row"><Sparkles size={12} />AI 読解でも同じ機器を確認しました（ルール抽出と一致）</div>}
      <div className="mt-8" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 12 }}>
        <div><div className="xs muted">外形 W×H×D</div><div className="num bold">{c.w ? `${c.w}×${c.h}×${c.d}` : '—'}</div></div>
        <div><div className="xs muted">発熱</div><div className="num bold">{c.heat_w != null ? `${c.heat_w} W` : '—'}</div></div>
        <div><div className="xs muted">単価</div><div className="num bold">{c.price != null ? yen(c.price) : <span style={{ color: 'var(--danger)' }}>未登録</span>}</div></div>
        <div><div className="xs muted">メーカー</div><div className="bold">{c.maker || '—'}</div></div>
      </div>
      {c.clearance && <div className="xs text-2 mt-4">放熱クリアランス：上 {c.clearance.top}mm・下 {c.clearance.bottom}mm・左右 {c.clearance.side}mm（マスタ値）</div>}
      {c.master_match?.kind === 'fuzzy' && (
        <div className="banner banner-amber mt-8" style={{ padding: '7px 10px', fontSize: 12 }}>
          <AlertOctagon size={14} />マスタに完全一致する型式がありません。近い候補：<b className="mono">{c.master_match.model}</b>
          <button className="btn btn-xs" onClick={() => act(() => api.componentAction(project.id, c.key, { model: c.master_match!.model }), '型式を候補に置き換えました')}>候補を採用</button>
        </div>
      )}
      {!isRec && (
        <div className="row-wrap mt-12">
          <label className="row small gap-4">型式<input className="input input-sm mono" style={{ width: 130 }} value={model} onChange={(e) => setModel(e.target.value)} /></label>
          <label className="row small gap-4">数量<input className="input input-sm num" style={{ width: 64 }} type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)} /></label>
          <button className="btn btn-xs btn-primary" disabled={!dirty} onClick={save}>保存</button>
          <span className="spacer" />
          {c.status !== 'confirmed' && !c.deleted && <button className="btn btn-xs btn-ok" onClick={() => act(() => api.componentAction(project.id, c.key, { confirmed: true }), `${c.name}を確定しました`)}><Check size={12} />確定</button>}
          {c.origin === 'manual'
            ? <button className="btn btn-xs btn-danger" onClick={() => act(() => api.componentReset(project.id, c.key), '手動追加の機器を削除しました')}><Trash2 size={12} />削除</button>
            : <button className="btn btn-xs btn-danger" onClick={() => act(() => api.componentAction(project.id, c.key, { deleted: !c.deleted }), c.deleted ? '削除を取り消しました' : '見積対象から外しました')}>{c.deleted ? <><RotateCcw size={12} />復元</> : <><Trash2 size={12} />対象外にする</>}</button>}
          {c.override && c.origin !== 'manual' && <button className="btn btn-xs btn-ghost" onClick={() => act(() => api.componentReset(project.id, c.key), '自動抽出の内容に戻しました')}><Undo2 size={12} />戻す</button>}
        </div>
      )}
      {isRec && <div className="xs text-2 mt-8">収容判定の放熱計算により自動追加された推奨品です。見積に含めるかは「収容判定」画面で切り替えられます。</div>}
    </motion.div>
  )
}

/** 回答を少しずつ表示する（最新の回答だけ）。 */
function Typewriter({ text, animate }: { text: string; animate: boolean }) {
  const [n, setN] = useState(animate ? 0 : text.length)
  useEffect(() => {
    if (!animate) { setN(text.length); return }
    let i = 0
    const t = setInterval(() => {
      i += Math.max(1, Math.round(text.length / 90))
      setN(Math.min(i, text.length))
      if (i >= text.length) clearInterval(t)
    }, 18)
    return () => clearInterval(t)
  }, [text, animate])
  return <>{text.slice(0, n)}{n < text.length && <span style={{ opacity: 0.5 }}>▍</span>}</>
}

function Chat({ ctx, label, onPick, focusSrc }: { ctx: Ctx; label: (id: string) => string; onPick: (s: Source, r: Source[]) => void; focusSrc: Source | null }) {
  const { project, act } = ctx
  const { ai } = useAi()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [animateIdx, setAnimateIdx] = useState(-1)
  const log = useRef<HTMLDivElement>(null)
  const chat: ChatMessage[] = project.chat || []
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' }) }, [chat.length, pending])

  const send = async (text: string) => {
    if (!text.trim() || pending) return
    setPending(text)
    setQ('')
    const ok = await act(() => api.aiAsk(project.id, text))
    if (ok) setAnimateIdx(chat.length + 1)
    setPending(null)
  }
  if (!ai.enabled) {
    return <div className="empty"><div className="empty-icon"><Bot size={26} /></div><h3>AI が接続されていません</h3><div className="small">マスタ・設定の「AI 設定」で OpenAI API を有効にすると、仕様書に質問できます。</div></div>
  }
  return (
    <div className="chat">
      <div className="chat-log" ref={log}>
        {chat.length === 0 && !pending && (
          <motion.div className="col gap-12" initial="hidden" animate="show" variants={stagger} style={{ alignItems: 'center', padding: '20px 0' }}>
            <motion.div variants={fadeUp} className="rv-orb" aria-hidden>
              <span className="rv-orb-ring" /><span className="rv-orb-core"><Bot size={28} /></span>
              <span className="rv-orb-sat s1" /><span className="rv-orb-sat s2" /><span className="rv-orb-sat s3" />
            </motion.div>
            <motion.div variants={fadeUp} className="rv-chat-title">仕様書について、なんでも聞いてください</motion.div>
            <motion.div variants={fadeUp} className="small text-2 center">登録資料だけを根拠に回答し、根拠の箇所をハイライトします。<br />資料に書かれていないことは「記載なし」と答えます。</motion.div>
            <motion.div variants={fadeUp} className="rv-chat-guards">
              <span><FileSearch size={11} />根拠を必ず表示</span><span><Check size={11} />引用を原文と照合</span><span><Sparkles size={11} />推測で答えない</span>
            </motion.div>
            <motion.div variants={stagger} className="rv-suggests">
              {SUGGESTIONS.map((s) => (
                <motion.button variants={fadeUp} whileHover={{ y: -2 }} whileTap={{ scale: 0.98 }} key={s} className="suggest" onClick={() => send(s)}>
                  <span className="suggest-ic"><MessageCircleQuestion size={13} /></span><span className="grow">{s}</span><ArrowRight size={13} className="suggest-go" />
                </motion.button>
              ))}
            </motion.div>
          </motion.div>
        )}
        <AnimatePresence initial={false}>
          {chat.map((m, i) => (
            <motion.div key={`${i}-${m.at}`} className="row gap-8" style={{ alignItems: 'flex-start', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}
              initial={{ opacity: 0, y: 12, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}>
              {m.role === 'assistant' && <div className="ai-avatar"><Sparkles size={15} /></div>}
              <div className={`bubble ${m.role}`}>
                {m.role === 'assistant' ? <Typewriter text={m.content} animate={i === animateIdx} /> : m.content}
                {m.role === 'assistant' && (m.citations || []).length > 0 && (
                  <div className="row-wrap mt-8" style={{ whiteSpace: 'normal' }}>
                    <span className="xs muted">根拠：</span>
                    <SourceChips sources={m.citations!} label={label} active={focusSrc} onPick={(s) => onPick(s, m.citations!)} />
                  </div>
                )}
                {m.role === 'assistant' && m.usage && (
                  <div className="xs muted mt-4" style={{ whiteSpace: 'normal' }}>
                    {m.usage.model} ・ {m.usage.seconds}秒{m.unverified ? ` ・ 原文で確認できない引用 ${m.unverified} 件は表示していません` : ''}
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {pending && (
            <motion.div key="pending" className="col gap-12" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="row" style={{ justifyContent: 'flex-end' }}><div className="bubble user">{pending}</div></div>
              <div className="row gap-8"><div className="ai-avatar"><Sparkles size={15} /></div><div className="bubble assistant"><span className="typing"><i /><i /><i /></span></div></div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <div className="chat-input">
        <input className="input grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="例：予備品には何が含まれますか？" aria-label="AI への質問"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) send(q) }} disabled={!!pending} />
        <button className="btn btn-magic" onClick={() => send(q)} disabled={!q.trim() || !!pending} aria-label="送信"><Send size={15} /></button>
        {chat.length > 0 && <button className="btn btn-ghost btn-icon" title="会話を消去" aria-label="会話を消去"
          onClick={async () => { if (await act(() => api.aiChatClear(project.id))) toast('会話を消去しました') }}><Eraser size={15} /></button>}
      </div>
    </div>
  )
}

// ---------- 確認パネル見出し・要確認リスト ----------

/** 構成機器の内訳（取付位置ごとの点数と、AI 確認・変更・追加の件数） */
function CompSummary({ comps }: { comps: Component[] }) {
  const live = comps.filter((c) => !c.deleted)
  const units = (m: string) => live.filter((c) => c.layout_mount === m).reduce((t, c) => t + (c.qty ?? 0), 0)
  const items = [
    { k: 'plate', label: '取付板', n: units('plate'), icon: <LayoutPanelTop size={13} /> },
    { k: 'terminal', label: '端子', n: units('terminal'), icon: <Cable size={13} /> },
    { k: 'door', label: '扉面', n: units('door'), icon: <DoorOpen size={13} /> },
  ]
  const flags = [
    { k: 'ai', label: 'AI でも確認', n: live.filter((c) => c.ai_verified).length },
    { k: 'chg', label: '変更反映', n: live.filter((c) => c.status === 'changed').length },
    { k: 'add', label: '追加・推奨', n: live.filter((c) => ['added', 'recommended', 'ai'].includes(c.status)).length },
  ].filter((f) => f.n > 0)
  return (
    <div className="rv-csum">
      <motion.div className="rv-csum-tiles" variants={stagger} initial="hidden" animate="show">
        {items.map((x) => (
          <motion.div key={x.k} variants={fadeUp} whileHover={{ y: -2 }} className={`rv-tile m-${x.k}`}>
            <span className="rv-tile-ic">{x.icon}</span>
            <span className="rv-tile-tx"><small>{x.label}</small><b><CountUp value={x.n} /><i>点</i></b></span>
          </motion.div>
        ))}
      </motion.div>
      {flags.length > 0 && (
        <div className="rv-csum-flags">{flags.map((f) => <span key={f.k} className={`rv-flag f-${f.k}`}>{f.k === 'ai' && <Sparkles size={10} />}{f.label}<b>{f.n}</b></span>)}</div>
      )}
    </div>
  )
}

const SETTLED: Field['status'][] = ['ok', 'confirmed', 'edited', 'resolved', 'changed']
const BLOCKING: Field['status'][] = ['conflict', 'missing']

const ISSUE_ICON: Record<string, LucideIcon> = {
  conflict: GitCompareArrows, missing: SearchX, review: Eye, asked: MessageCircleQuestion, ai_component: Sparkles,
  no_master: PackageX, fit: Boxes, thermal: Thermometer, rfq: ReceiptJapaneseYen, expired: CalendarX2, document: FileWarning, drawing: ScanLine,
}

/** 確定率のリング（グラデーションの弧が伸び、中央で % がカウントアップ） */
function ProgressRing({ value }: { value: number }) {
  const R = 27
  const C = 2 * Math.PI * R
  return (
    <div className="rv-ring" aria-label={`確定率 ${Math.round(value * 100)}%`}>
      <span className="rv-ring-halo" aria-hidden />
      <svg viewBox="0 0 64 64" aria-hidden>
        <defs>
          <linearGradient id="rv-ring-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#18b47d" /><stop offset="55%" stopColor="#3d55e6" /><stop offset="100%" stopColor="#d4a64a" />
          </linearGradient>
        </defs>
        <circle cx="32" cy="32" r={R} className="rv-ring-track" />
        <motion.circle cx="32" cy="32" r={R} className="rv-ring-fill" stroke="url(#rv-ring-grad)" strokeDasharray={C}
          initial={{ strokeDashoffset: C }} animate={{ strokeDashoffset: C * (1 - value) }} transition={{ duration: 1.5, ease: [0.22, 1, 0.36, 1] }} />
      </svg>
      <span className="rv-ring-pct"><CountUp value={Math.round(value * 100)} duration={1.4} /><small>%</small></span>
    </div>
  )
}

function ReviewHead({ fields, a, tabs }: { fields: Field[]; a: Analysis; tabs: React.ReactNode }) {
  const relevant = fields.filter((f) => f.status !== 'empty')
  const settled = relevant.filter((f) => SETTLED.includes(f.status)).length
  const blocking = relevant.filter((f) => BLOCKING.includes(f.status)).length
  const pending = relevant.length - settled - blocking
  const total = Math.max(1, relevant.length)
  const segs = [
    { k: 'ok', n: settled, label: '確定・整合' },
    { k: 'warn', n: pending, label: '要確認' },
    { k: 'hot', n: blocking, label: '矛盾・記載なし' },
  ]
  return (
    <div className="rv-head">
      <div className="rv-head-bg" aria-hidden><span className="b1" /><span className="b2" /></div>
      <div className="rv-head-main">
        <ProgressRing value={settled / total} />
        <div className="grow">
          <div className="rv-eyebrow"><span className="hishi sm" />確認の進捗</div>
          <div className="rv-count">
            <b><CountUp value={settled} /></b><span className="rv-of">/ {relevant.length}</span><span className="rv-unit">項目が確定・整合</span>
          </div>
          <div className="rv-badges">
            {a.ai.used && (
              <motion.span className="rv-agree" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 420, damping: 18, delay: 0.35 }} title="ルール抽出と AI 読解が独立に同じ値を読んだ項目数">
                <Sparkles size={11} className="rv-agree-spark" />ルール×AI 一致 <b>{a.ai.agreed}</b>
              </motion.span>
            )}
            {a.stats.blocking > 0
              ? <span className="rv-gate hot"><i />承認前に解決 <b>{a.stats.blocking}</b> 件</span>
              : <span className="rv-gate ok"><ShieldCheck size={12} />承認可能</span>}
          </div>
        </div>
      </div>
      <div className="rv-dist" role="img" aria-label={segs.map((s) => `${s.label} ${s.n}`).join('、')}>
        {segs.filter((s) => s.n > 0).map((s, i) => (
          <motion.span key={s.k} className={`rv-seg ${s.k}`} style={{ flexGrow: s.n }} title={`${s.label} ${s.n} 項目`}
            initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: 0.25 + i * 0.18, duration: 0.7, ease: [0.22, 1, 0.36, 1] }} />
        ))}
      </div>
      <div className="rv-legend">
        {segs.map((s) => <span key={s.k} className={`rv-lg ${s.k}`}><i />{s.label}<b>{s.n}</b></span>)}
        <span className="spacer" />
        <span className="rv-meta"><ListChecks size={12} />機器 {a.stats.components} 件 ・ 解析 {dt(a.analyzed_at)}</span>
      </div>
      <div className="rv-tabs">{tabs}</div>
    </div>
  )
}

function GroupTitle({ tone, icon, children, n }: { tone: 'ai' | 'field' | 'other' | 'kin' | 'teal'; icon: React.ReactNode; children: React.ReactNode; n?: number }) {
  return (
    <div className={`group-title rv-group g-${tone}`}>
      <span className="rv-group-ic">{icon}</span>{children}{n != null && <span className="rv-group-n">{n}</span>}<span className="rv-group-line" />
    </div>
  )
}

const issueIn: Variants = {
  hidden: { opacity: 0, x: 26, filter: 'blur(4px)' },
  show: { opacity: 1, x: 0, filter: 'blur(0px)', transition: { type: 'spring', stiffness: 240, damping: 24 } },
}

/** 要確認の1行（左の帯・種別アイコン・マウス追従の光） */
function IssueRow({ i, onOpen }: { i: Issue; onOpen: () => void }) {
  const Icon = ISSUE_ICON[i.type] ?? Info
  const cut = i.title.indexOf('：')
  const head = cut > 0 ? i.title.slice(0, cut) : i.title
  const rest = cut > 0 ? i.title.slice(cut + 1) : ''
  return (
    <motion.div variants={issueIn} role="button" tabIndex={0} className={`rv-issue sev-${i.severity} ${i.blocking ? 'blocking' : ''}`}
      onClick={onOpen} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
      onMouseMove={spot}>
      <span className="rv-rail" aria-hidden />
      <span className="rv-ic" aria-hidden><Icon size={16} strokeWidth={2.2} />{i.blocking && <i className="rv-ic-ping" />}</span>
      <div className="grow">
        <div className="rv-title-row">
          <span className="rv-title"><b>{head}</b>{rest && <><span className="rv-colon">：</span><span className="rv-rest">{rest}</span></>}</span>
          {i.blocking && <span className="rv-must">承認前に解決</span>}
          {i.type === 'ai_component' && <Badge cls="badge-ai">AI</Badge>}
        </div>
        <div className="rv-detail">{i.detail}</div>
      </div>
      <span className="rv-go" aria-hidden><ArrowRight size={14} /></span>
    </motion.div>
  )
}

export default function ReviewTab({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const a = project.analysis!
  const label = useDocLabel(project.documents)
  const [tab, setTab] = useState<PanelTab>('issues')
  const [sel, setSel] = useState<Sel>(null)
  const [focus, setFocus] = useState<Source | null>(null)
  const [related, setRelated] = useState<Source[]>([])
  const [adding, setAdding] = useState(false)
  const [newComp, setNewComp] = useState({ name: '', model: '', qty: '1', mount: 'plate' })

  const fields = a.fields
  const byGroup = (g: string) => fields.filter((f) => f.group === g)
  const fieldIssues = a.issues.filter((i) => i.target?.kind === 'field' || i.target?.kind === 'component')
  const otherIssues = a.issues.filter((i) => !(i.target?.kind === 'field' || i.target?.kind === 'component'))

  const pick = (s: Source | null, rel: Source[] = []) => { setFocus(s); setRelated(rel) }
  const selectField = (f: Field) => {
    setSel({ kind: 'field', key: f.key })
    const src = f.status === 'conflict' && f.candidates[f.provisional ?? 0] ? f.candidates[f.provisional ?? 0].sources[0] : f.sources[0]
    pick(src || null, f.sources)
  }
  const selectComp = (c: Component) => {
    setSel(sel?.key === c.key ? null : { kind: 'component', key: c.key })
    pick(c.sources[0] || null, c.sources)
  }
  const openIssue = (i: Issue) => {
    const t = i.target
    if (!t) return
    if (t.kind === 'field') {
      const f = fields.find((x) => x.key === t.key)
      if (f) { setTab(f.group === 'conditions' ? 'conditions' : 'panel'); selectField(f) }
    } else if (t.kind === 'component') {
      const c = a.components.find((x) => x.key === t.key)
      if (c) { setTab('components'); setSel({ kind: 'component', key: c.key }); pick(c.sources[0] || null, c.sources) }
    } else if (t.kind === 'fit') ctx.go('fit')
    else if (t.kind === 'estimate') ctx.go('estimate')
    else if (t.kind === 'document') ctx.go('documents')
  }

  useEffect(() => {
    const f = ctx.focus
    if (!f) return
    if (f.kind === 'field' || f.kind === 'component') openIssue({ id: '', severity: 'low', type: '', title: '', detail: '', target: f as Issue['target'] })
  }, [ctx.focus]) // eslint-disable-line react-hooks/exhaustive-deps

  // タブを切り替えたら先頭から表示する（選択中の行があれば、その後の処理でそこまでスクロール）
  const body = useRef<HTMLDivElement>(null)
  useEffect(() => { body.current?.scrollTo({ top: 0 }) }, [tab])

  useEffect(() => {
    const t = setTimeout(() => document.querySelector('.panel-body .focused')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 80)
    return () => clearTimeout(t)
  }, [sel, tab])

  const comps = a.components

  const renderFields = (list: Field[]) => (
    <motion.div variants={stagger} initial="hidden" animate="show">
      {list.map((f) => (
        <FieldRow key={f.key} f={f} ctx={ctx} label={label} focusSrc={focus}
          selected={sel?.kind === 'field' && sel.key === f.key} onSelect={() => selectField(f)}
          onPick={(s, r) => { setSel({ kind: 'field', key: f.key }); pick(s, r) }} />
      ))}
    </motion.div>
  )
  const issueRow = (i: Issue) => <IssueRow key={i.id} i={i} onOpen={() => openIssue(i)} />

  return (
    <div style={{ flex: 1, minHeight: 0 }}>
      <div className="review">
        <SourceViewer projectId={project.id} docs={project.documents} focus={focus} related={related} />
        <div className="panel">
          <ReviewHead fields={fields} a={a} tabs={
            <SegTabs id="review" value={tab} onChange={setTab} items={[
              { id: 'issues', label: '要確認', n: fieldIssues.length, tone: a.stats.blocking ? 'red' : undefined },
              { id: 'panel', label: '盤仕様' },
              { id: 'components', label: '構成機器', n: comps.filter((c) => !c.deleted).length },
              { id: 'conditions', label: '条件' },
              { id: 'risks', label: 'リスク', n: a.risks.length },
              { id: 'chat', label: <><Sparkles size={12} />AIに質問</>, n: (project.chat || []).filter((m) => m.role === 'user').length || undefined, tone: 'ai' },
            ]} />
          } />
          <div className="panel-body" ref={body} style={tab === 'chat' ? { overflow: 'hidden' } : undefined}>
            <motion.div key={tab} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}
              style={tab === 'chat' ? { height: '100%' } : undefined}>
                {tab === 'issues' && (
                  <motion.div variants={stagger} initial="hidden" animate="show">
                    {a.ai_notes.length > 0 && <GroupTitle tone="ai" icon={<Sparkles size={11} />} n={a.ai_notes.length}>AI が見つけた訂正・確定</GroupTitle>}
                    {a.ai_notes.map((n, i) => (
                      <motion.div key={i} variants={fadeUp} className={`rv-note ${sel?.kind === 'note' && sel.key === String(i) ? 'focused' : ''}`}
                        onClick={() => { setSel({ kind: 'note', key: String(i) }); pick(n.source, [n.source]) }}>
                        <div className="rv-note-card">
                          <span className="rv-note-orb" aria-hidden><Sparkles size={15} /></span>
                          <div className="grow">
                            <div className="frow-top"><span className="rv-note-tag">AI 所見</span><span className="spacer" />
                              <SourceChips sources={[n.source]} label={label} active={focus} onPick={(s) => pick(s, [s])} /></div>
                            <div className="rv-note-text">{n.summary}</div>
                          </div>
                        </div>
                      </motion.div>
                    ))}
                    {fieldIssues.length === 0 && (
                      <div className="empty"><div className="empty-icon" style={{ background: 'var(--grad-ok)' }}><Check size={26} /></div>
                        <h3>抽出内容の要確認事項はありません</h3><div className="small">収容判定・見積の確認に進めます。</div>
                        <button className="btn btn-primary mt-16" onClick={() => ctx.go('fit')}>収容判定へ<ArrowRight size={15} /></button></div>
                    )}
                    {fieldIssues.length > 0 && <GroupTitle tone="field" icon={<FileSearch size={11} />} n={fieldIssues.length}>抽出内容</GroupTitle>}
                    {fieldIssues.map(issueRow)}
                    {otherIssues.length > 0 && <GroupTitle tone="other" icon={<Boxes size={11} />} n={otherIssues.length}>判定・見積・資料</GroupTitle>}
                    {otherIssues.map(issueRow)}
                  </motion.div>
                )}
                {tab === 'panel' && (
                  <>
                    <GroupTitle tone="kin" icon={<Building2 size={11} />} n={byGroup('project').length}>案件情報</GroupTitle>
                    {renderFields(byGroup('project'))}
                    <GroupTitle tone="field" icon={<LayoutPanelTop size={11} />} n={byGroup('panel').length}>盤仕様</GroupTitle>
                    {renderFields(byGroup('panel'))}
                  </>
                )}
                {tab === 'conditions' && (
                  <>
                    <GroupTitle tone="teal" icon={<ClipboardList size={11} />} n={byGroup('conditions').length}>見積条件</GroupTitle>
                    {renderFields(byGroup('conditions'))}
                    <GroupTitle tone="kin" icon={<ScrollText size={11} />} n={a.instructions.length}>指示事項（本文から抽出）</GroupTitle>
                    <motion.div variants={stagger} initial="hidden" animate="show">
                      {a.instructions.map((ins, i) => (
                        <motion.div key={i} variants={fadeUp} className={`rv-instr ${sel?.kind === 'instruction' && sel.key === String(i) ? 'focused' : ''}`} onMouseMove={spot}
                          onClick={() => { setSel({ kind: 'instruction', key: String(i) }); pick(ins.source, [ins.source]) }}>
                          <span className="rv-instr-no">{String(i + 1).padStart(2, '0')}</span>
                          <div className="grow">
                            <div className="frow-top"><span className="rv-instr-sec">{ins.section}</span><span className="spacer" />
                              <SourceChips sources={[ins.source]} label={label} active={focus} onPick={(s) => pick(s, [s])} /></div>
                            <div className="rv-instr-text">{ins.text}</div>
                          </div>
                        </motion.div>
                      ))}
                    </motion.div>
                  </>
                )}
                {tab === 'risks' && (
                  <motion.div variants={stagger} initial="hidden" animate="show">
                    <GroupTitle tone="other" icon={<ShieldAlert size={11} />} n={a.risks.length}>見積漏れにつながりやすい記載</GroupTitle>
                    {a.risks.map((r, i) => (
                      <motion.div key={i} variants={issueIn} className={`rv-risk ${sel?.kind === 'risk' && sel.key === String(i) ? 'focused' : ''}`} onMouseMove={spot}
                        onClick={() => { setSel({ kind: 'risk', key: String(i) }); pick(r.source, [r.source]) }}>
                        <span className="rv-risk-ic" aria-hidden><ShieldAlert size={17} /></span>
                        <div className="grow">
                          <div className="frow-top"><span className="rv-risk-title">{r.label}</span><span className="spacer" />
                            <SourceChips sources={[r.source]} label={label} active={focus} onPick={(s) => pick(s, [s])} /></div>
                          <blockquote className="rv-quote">{r.text}</blockquote>
                          <div className="rv-impact"><b>影響</b>{r.impact}</div>
                        </div>
                      </motion.div>
                    ))}
                  </motion.div>
                )}
                {tab === 'components' && (
                  <>
                    <CompSummary comps={comps} />
                    <table className="table rv-ctable" style={{ fontSize: 12.5 }}>
                      <thead><tr><th style={{ width: 40 }}>No</th><th>品名</th><th>型式</th><th className="right">数量</th><th>取付</th><th>状態</th></tr></thead>
                      <motion.tbody variants={stagger} initial="hidden" animate="show">
                        {comps.map((c) => {
                          const open = sel?.kind === 'component' && sel.key === c.key
                          const st = COMP_STATUS[c.status]
                          return [
                            <motion.tr key={c.key} variants={fadeUp} className={`clickable rv-crow st-${c.status} ${open ? 'selected' : ''}`} onClick={() => selectComp(c)} style={c.deleted ? { opacity: 0.5, textDecoration: 'line-through' } : undefined}>
                              <td><span className="rv-no">{c.no ?? '—'}</span></td>
                              <td>
                                <div className="rv-cname">{c.name}{c.ai_verified && <Sparkles size={11} className="rv-cai" aria-label="AI でも確認" />}</div>
                                {(c.aliased || c.name_note) && <div className="rv-raw">原文：{c.raw_name}</div>}
                              </td>
                              <td className="nowrap"><span className="rv-model">{c.model || '—'}</span></td>
                              <td className="right"><span className="rv-qty"><small>×</small>{c.qty ?? '—'}</span></td>
                              <td className="nowrap">{c.layout_mount ? <span className={`rv-mount m-${c.layout_mount}`} title={MOUNT_JA[c.layout_mount]}>{MOUNT_ICON[c.layout_mount]}<span className="rv-mount-tx">{MOUNT_JA[c.layout_mount]}</span></span> : '—'}</td>
                              <td><Badge cls={st.cls}>{st.label}</Badge></td>
                            </motion.tr>,
                            open && <tr key={`${c.key}-d`} className="selected"><td colSpan={6}>
                              <ComponentDetail c={c} ctx={ctx} label={label} focusSrc={focus} onPick={(s, r) => pick(s, r)} />
                            </td></tr>,
                          ]
                        })}
                      </motion.tbody>
                    </table>
                    <div className="rv-add">
                      <button className="btn btn-sm rv-add-btn" onClick={() => setAdding(true)}><Plus size={14} />機器を手動で追加</button>
                    </div>
                  </>
                )}
                {tab === 'chat' && <Chat ctx={ctx} label={label} focusSrc={focus} onPick={(s, r) => { setSel({ kind: 'chat', key: '' }); pick(s, r) }} />}
            </motion.div>
          </div>
        </div>
      </div>
      {adding && (
        <Modal title="構成機器を追加" onClose={() => setAdding(false)}
          footer={<><button className="btn" onClick={() => setAdding(false)}>キャンセル</button>
            <button className="btn btn-primary" disabled={!newComp.name.trim()} onClick={async () => {
              if (await act(() => api.componentAdd(project.id, { ...newComp, qty: Number(newComp.qty) }), '機器を追加しました')) {
                setAdding(false); setNewComp({ name: '', model: '', qty: '1', mount: 'plate' })
              }
            }}>追加</button></>}>
          <div className="col gap-12">
            <div className="field-group"><label className="label">品名 *</label><input className="input" autoFocus value={newComp.name} onChange={(e) => setNewComp({ ...newComp, name: e.target.value })} /></div>
            <div className="row gap-12">
              <div className="field-group grow"><label className="label">型式（マスタと照合されます）</label><input className="input mono" value={newComp.model} onChange={(e) => setNewComp({ ...newComp, model: e.target.value })} placeholder="例：RY-4C" /></div>
              <div className="field-group" style={{ width: 90 }}><label className="label">数量</label><input className="input" type="number" min={1} value={newComp.qty} onChange={(e) => setNewComp({ ...newComp, qty: e.target.value })} /></div>
            </div>
            <div className="field-group"><label className="label">取付位置（マスタ未登録時に使用）</label>
              <select className="select" value={newComp.mount} onChange={(e) => setNewComp({ ...newComp, mount: e.target.value })}>
                <option value="plate">取付板</option><option value="door">扉面</option>
              </select></div>
          </div>
        </Modal>
      )}
    </div>
  )
}
