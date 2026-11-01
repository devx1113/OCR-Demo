import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, GitCompareArrows, History, Layers, Minus, Plus } from 'lucide-react'
import { api } from '../api'
import type { RevisionDiff } from '../types'
import { Empty, Spinner, dt, fadeUp, stagger, yen } from '../ui'
import type { Ctx } from './ProjectPage'

const COLOR: Record<string, string> = {
  承認: 'var(--ok)', 承認取消: 'var(--danger)', 解析実行: 'var(--ai-500)', 資料登録: 'var(--teal)', 見積書出力: 'var(--ok)',
  矛盾の解決: 'var(--murasaki-500)', 質疑へ回す: 'var(--murasaki-500)', 'AI 読解': '#b14dff', 'AI-OCR': '#b14dff', 'AI 設計レビュー': '#b14dff',
  'AI メール文案': '#ff5c9d', 承認依頼: 'var(--info)', 差戻し: 'var(--danger)', 承認依頼の取下げ: 'var(--warn)',
}

const signed = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : '±'}${yen(Math.abs(n))}`
const pct = (n: number) => `${(n * 100).toFixed(1)}%`

/** 2つの版（または版と作業中の内容）の差分 */
function DiffView({ d }: { d: RevisionDiff }) {
  const t = d.totals
  const label = (r: number | string) => (r === 'current' ? '作業中' : `第${r}版`)
  if (d.changes === 0 && t.sale_total.delta === 0) {
    return <div className="diff-same">{label(d.a.rev)} と {label(d.b.rev)} の内容に違いはありません。</div>
  }
  return (
    <motion.div className="col gap-12" variants={stagger} initial="hidden" animate="show">
      <motion.div className="diff-totals" variants={fadeUp}>
        {([['sale_total', '見積金額（税抜）'], ['cost_total', '原価合計']] as const).map(([k, l]) => (
          <div key={k} className="diff-total">
            <small>{l}</small>
            <div className="row gap-8"><span className="num muted">{yen(t[k].a)}</span><ArrowRight size={13} /><b className="num">{yen(t[k].b)}</b></div>
            <span className={`diff-delta ${t[k].delta > 0 ? 'up' : t[k].delta < 0 ? 'down' : ''}`}>{signed(t[k].delta)}</span>
          </div>
        ))}
        <div className="diff-total">
          <small>利益率</small>
          <div className="row gap-8"><span className="num muted">{pct(t.margin.a)}</span><ArrowRight size={13} /><b className="num">{pct(t.margin.b)}</b></div>
          <span className={`diff-delta ${t.margin.delta > 0 ? 'up' : t.margin.delta < 0 ? 'down' : ''}`}>{t.margin.delta === 0 ? '±0' : `${t.margin.delta > 0 ? '+' : '−'}${(Math.abs(t.margin.delta) * 100).toFixed(1)}pt`}</span>
        </div>
      </motion.div>

      {d.lines.length > 0 && (
        <motion.div variants={fadeUp}>
          <div className="diff-h">見積明細（{d.lines.length}）</div>
          {d.lines.map((l) => (
            <div key={l.name} className={`diff-row k-${l.kind}`}>
              <span className="diff-k">{l.kind === 'added' ? <Plus size={11} /> : l.kind === 'removed' ? <Minus size={11} /> : <ArrowRight size={11} />}</span>
              <span className="grow">{l.name}</span>
              {l.kind === 'changed' && <span className="small muted num">{l.a!.qty}{l.a!.unit} × {yen(l.a!.unit_price)} → {l.b!.qty}{l.b!.unit} × {yen(l.b!.unit_price)}</span>}
              <b className="num">{l.kind === 'changed' ? signed(l.delta!) : l.kind === 'added' ? `+${yen(l.b!.amount)}` : `−${yen(l.a!.amount)}`}</b>
            </div>
          ))}
        </motion.div>
      )}
      {(d.fields.length > 0 || d.other.length > 0) && (
        <motion.div variants={fadeUp}>
          <div className="diff-h">仕様・条件の値（{d.fields.length + d.other.length}）</div>
          {[...d.other, ...d.fields].map((f) => (
            <div key={f.label} className="diff-row k-changed">
              <span className="diff-k"><ArrowRight size={11} /></span>
              <span className="diff-label">{f.label}</span>
              <span className="grow small"><s className="muted">{f.a ?? '（なし）'}</s> → <b>{f.b ?? '（なし）'}</b></span>
            </div>
          ))}
        </motion.div>
      )}
      {d.components.length > 0 && (
        <motion.div variants={fadeUp}>
          <div className="diff-h">構成機器（{d.components.length}）</div>
          {d.components.map((c) => (
            <div key={c.name} className={`diff-row k-${c.kind}`}>
              <span className="diff-k">{c.kind === 'added' ? <Plus size={11} /> : c.kind === 'removed' ? <Minus size={11} /> : <ArrowRight size={11} />}</span>
              <span className="grow">{c.name}</span>
              <span className="small num">
                {c.kind === 'changed' ? <>{c.a!.model} ×{c.a!.qty} → <b>{c.b!.model} ×{c.b!.qty}</b></> : c.kind === 'added' ? <b>{c.b!.model} ×{c.b!.qty}</b> : <s>{c.a!.model} ×{c.a!.qty}</s>}
              </span>
            </div>
          ))}
        </motion.div>
      )}
      {(d.conditions.added.length > 0 || d.conditions.removed.length > 0) && (
        <motion.div variants={fadeUp}>
          <div className="diff-h">見積書の前提条件</div>
          {d.conditions.added.map((c) => <div key={c} className="diff-row k-added"><span className="diff-k"><Plus size={11} /></span><span className="grow small">{c}</span></div>)}
          {d.conditions.removed.map((c) => <div key={c} className="diff-row k-removed"><span className="diff-k"><Minus size={11} /></span><span className="grow small"><s>{c}</s></span></div>)}
        </motion.div>
      )}
    </motion.div>
  )
}

function Revisions({ ctx }: { ctx: Ctx }) {
  const { project } = ctx
  const revs = project.revisions || []
  const latest = revs.length ? revs[revs.length - 1].rev : null
  const [a, setA] = useState<string>(revs.length > 1 ? String(revs[revs.length - 2].rev) : latest ? String(latest) : '')
  const [b, setB] = useState<string>(revs.length > 1 ? String(latest) : 'current')
  const [d, setD] = useState<RevisionDiff | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!a || !project.analysis) return
    let alive = true
    setBusy(true)
    api.compareRevisions(project.id, a, b).then((r) => alive && setD(r)).catch(() => alive && setD(null)).finally(() => alive && setBusy(false))
    return () => { alive = false }
  }, [a, b, project.id, project.rev, project.analysis])

  return (
    <div className="card">
      <div className="card-head"><Layers size={18} /><h3>見積の版</h3><span className="spacer" /><span className="small muted">承認のたびに版を記録します</span></div>
      {revs.length === 0 ? (
        <div className="card-body"><Empty icon={<Layers size={24} />} title="まだ承認された版はありません">設計課長が承認すると「第1版」として記録され、以降の変更と比較できます。</Empty></div>
      ) : (
        <div className="card-body col gap-16">
          <motion.div className="rev-list" variants={stagger} initial="hidden" animate="show">
            {[...revs].reverse().map((r) => (
              <motion.div key={r.rev} className={`rev-card ${String(r.rev) === a || String(r.rev) === b ? 'on' : ''} ${r.rev === latest && project.approval?.status === 'approved' ? 'current' : ''}`} variants={fadeUp}>
                <div className="rev-no">第{r.rev}版</div>
                <div className="rev-amt num">{yen(r.sale_total)}</div>
                <div className="xs text-2">承認 {r.approved_by}・{dt(r.at)}</div>
                {r.requested_by && <div className="xs muted">依頼 {r.requested_by}</div>}
                <div className="xs muted">利益率 {pct(r.margin)}{r.enclosure ? `・${r.enclosure}` : ''}</div>
                {r.comment && <div className="xs mt-4">「{r.comment}」</div>}
              </motion.div>
            ))}
          </motion.div>
          <div className="rev-compare">
            <GitCompareArrows size={16} />
            <select className="select input-sm" value={a} onChange={(e) => setA(e.target.value)} aria-label="比較元の版">
              {revs.map((r) => <option key={r.rev} value={r.rev}>第{r.rev}版</option>)}
            </select>
            <ArrowRight size={14} />
            <select className="select input-sm" value={b} onChange={(e) => setB(e.target.value)} aria-label="比較先の版">
              {revs.map((r) => <option key={r.rev} value={r.rev}>第{r.rev}版</option>)}
              <option value="current">作業中の内容</option>
            </select>
            <span className="spacer" />
            {busy && <Spinner size={14} />}
            {d && <span className="small muted">変更 {d.changes} 件</span>}
          </div>
          {d && <motion.div key={`${a}-${b}-${project.rev}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}><DiffView d={d} /></motion.div>}
        </div>
      )}
    </div>
  )
}

export default function HistoryTab({ ctx }: { ctx: Ctx }) {
  const h = ctx.project.history
  const [filter, setFilter] = useState('')
  const users = Array.from(new Set(h.map((x) => x.user)))
  const list = filter ? h.filter((x) => x.user === filter) : h
  return (
    <div className="page">
      <div className="page-narrow col gap-20" style={{ maxWidth: 960 }}>
        <Revisions ctx={ctx} />
        <div className="card">
          <div className="card-head">
            <History size={18} /><h3>操作・変更履歴</h3><span className="spacer" />
            <select className="select input-sm" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="担当者で絞り込み">
              <option value="">全担当者</option>
              {users.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
          <div className="card-body">
            {list.length === 0 ? <Empty icon={<History size={24} />} title="履歴はまだありません" /> : (
              <motion.div className="timeline" variants={stagger} initial="hidden" animate="show">
                {list.map((x, i) => (
                  <motion.div key={i} className="tl-item" variants={fadeUp}>
                    <div className="tl-dot" style={{ borderColor: COLOR[x.action] || 'var(--border-strong)' }} />
                    <div className="row"><b>{x.action}</b><span className="small muted">{x.user}</span><span className="spacer" /><span className="xs muted num">{dt(x.at)}</span></div>
                    {x.detail && <div className="small text-2 mt-4">{x.detail}</div>}
                  </motion.div>
                ))}
              </motion.div>
            )}
          </div>
          <div className="card-foot xs muted">修正理由・承認者・出力日時はすべて記録され、見積根拠書にも出力されます。</div>
        </div>
      </div>
    </div>
  )
}
