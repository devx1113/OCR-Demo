import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Archive, Check, History, Minus, Ruler, TriangleAlert } from 'lucide-react'
import { api } from '../api'
import { navigate } from '../App'
import type { Project, SimilarCase, SimilarResult } from '../types'
import { Badge, Spinner, fadeUp, pct, stagger, yen } from '../ui'

/** 解析結果が変わったときだけ取り直す（金額・筐体・機器構成が変わると類似度も変わる） */
export function useSimilar(project: Project) {
  const [r, setR] = useState<SimilarResult | null>(null)
  const [err, setErr] = useState('')
  const key = project.analysis?.analyzed_at
  useEffect(() => {
    let alive = true
    api.similar(project.id).then((x) => alive && setR(x)).catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [project.id, key])
  return { r, err }
}

function resultBadge(c: SimilarCase) {
  if (c.source === 'system') return <Badge cls="badge-blue">{c.result}</Badge>
  return <Badge cls={c.result === '受注' ? 'badge-green' : 'badge-gray'}>{c.result}</Badge>
}

function Score({ v }: { v: number }) {
  const r = 17
  const c = 2 * Math.PI * r
  return (
    <svg className="sim-score" width={44} height={44} viewBox="0 0 44 44" aria-label={`類似度 ${v}`}>
      <circle cx={22} cy={22} r={r} className="track" />
      <motion.circle cx={22} cy={22} r={r} className="bar" strokeDasharray={c} initial={{ strokeDashoffset: c }}
        animate={{ strokeDashoffset: c * (1 - v / 100) }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
      <text x={22} y={26} textAnchor="middle">{v}</text>
    </svg>
  )
}

/** 類似案件の金額の範囲（最小〜最大）と平均の中で、今回の金額がどこにあるか */
function PriceRange({ p }: { p: NonNullable<SimilarResult['price']> }) {
  const lo = Math.min(p.min, p.current) * 0.94
  const hi = Math.max(p.max, p.current) * 1.04
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  const word = p.delta_rate > 0 ? '高い' : '低い'
  return (
    <div className="sim-range">
      <div className="sim-range-track">
        <span className="band" style={{ left: x(p.min), width: `calc(${x(p.max)} - ${x(p.min)})` }} />
        <span className="avg" style={{ left: x(p.avg) }} title={`平均 ${yen(p.avg)}`} />
        <motion.span className={`cur ${p.position}`} initial={{ left: x(p.avg), opacity: 0 }} animate={{ left: x(p.current), opacity: 1 }}
          transition={{ delay: 0.3, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
      </div>
      <div className="sim-range-labels">
        <span>{yen(p.min)}</span><span className="muted">類似上位 {p.n} 件の範囲・平均 {yen(p.avg)}</span><span>{yen(p.max)}</span>
      </div>
      <div className={`small mt-8 ${p.position === 'within' ? 'text-2' : ''}`} style={p.position === 'within' ? undefined : { color: 'var(--warn)' }}>
        {p.position !== 'within' && <TriangleAlert size={13} style={{ verticalAlign: -2, marginRight: 4 }} />}
        今回 <b className="num">{yen(p.current)}</b> は平均より {pct(Math.abs(p.delta_rate), 0)} {word}
        {p.position === 'within' ? '（類似案件の範囲内）' : p.position === 'low' ? '。類似案件の最低額を下回っています（見積漏れがないか確認）' : '。類似案件の最高額を上回っています'}
      </div>
    </div>
  )
}

function CaseRow({ c, i }: { c: SimilarCase; i: number }) {
  return (
    <motion.div className={`sim-case ${c.source === 'system' ? 'clickable' : ''}`} variants={fadeUp} data-testid="similar-case"
      onClick={() => c.project_id && navigate(`/projects/${c.project_id}/estimate`)}>
      <Score v={c.score} />
      <div className="grow" style={{ minWidth: 0 }}>
        <div className="row-wrap" style={{ gap: 6 }}>
          <b className="head">{c.name}</b>{resultBadge(c)}{i === 0 && c.score >= 80 && <Badge cls="badge-purple">最も近い</Badge>}
        </div>
        <div className="xs muted">{c.quote_no} ・ {c.date} ・ {c.customer}{c.designer ? ` ・ ${c.designer}` : ''}</div>
        <div className="sim-chips">
          {c.match.map((m) => <span key={m} className="ok"><Check size={11} />{m}</span>)}
          {c.diff.map((m) => <span key={m} className="diff"><Minus size={11} />{m}</span>)}
        </div>
        {c.note && <div className="xs text-2 mt-4 sim-note">{c.note}</div>}
      </div>
      <div className="right nowrap">
        <div className="bold num">{c.sale_total != null ? yen(c.sale_total) : '—'}</div>
        <div className="xs muted">{c.enclosure}</div>
      </div>
    </motion.div>
  )
}

/** 見積画面：類似過去案件と金額の妥当性（C12） */
export function SimilarCard({ project }: { project: Project }) {
  const { r, err } = useSimilar(project)
  return (
    <motion.div className="card" variants={fadeUp} data-testid="similar-card">
      <div className="card-head"><History size={17} color="var(--ai-500)" /><h3>類似過去案件</h3><span className="spacer" />
        {r && <span className="small muted">過去 {r.searched} 件から検索 ・ 仕様・構成機器・盤サイズで比較</span>}</div>
      <div className="card-body col gap-12">
        {err && <div className="small muted">{err}</div>}
        {!r && !err && <Spinner />}
        {r?.price && <PriceRange p={r.price} />}
        {r && (
          <motion.div className="col gap-8" variants={stagger} initial="hidden" animate="show">
            {r.items.map((c, i) => <CaseRow key={c.quote_no + c.source} c={c} i={i} />)}
          </motion.div>
        )}
        <div className="xs muted">類似度は用途・盤形式・電圧・構成機器・インバータ容量・盤サイズの一致度の加重平均です。見積の値は変えず、判断の参考として示します。</div>
      </div>
    </motion.div>
  )
}

/** 収容判定画面：類似案件で最終的に採用した盤サイズ */
export function SimilarSizes({ project }: { project: Project }) {
  const { r } = useSimilar(project)
  if (!r || !r.sizes.length) return null
  const top = r.items[0]
  const max = Math.max(...r.sizes.map((s) => s.n))
  return (
    <motion.div className="card" variants={fadeUp} data-testid="similar-sizes">
      <div className="card-head"><Ruler size={17} color="var(--ai-500)" /><h3>類似案件の最終盤サイズ</h3><span className="spacer" />
        <button className="btn btn-xs btn-ghost" onClick={() => navigate(`/projects/${project.id}/estimate`)}><Archive size={12} />類似案件を見る</button></div>
      <div className="card-body col gap-8">
        {r.sizes.map((s) => (
          <div key={s.enclosure} className={`sim-size ${s.enclosure === r.current.enclosure ? 'current' : ''}`}>
            <span className="grow small">{s.enclosure}</span>
            <span className="sim-size-bar"><motion.span initial={{ width: 0 }} animate={{ width: `${(s.n / max) * 100}%` }} transition={{ duration: 0.7 }} /></span>
            <b className="num small">{s.n} 件</b>
          </div>
        ))}
        {top?.note && <div className="banner banner-blue small mt-4" style={{ alignItems: 'flex-start' }}><History size={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <span><b>{top.quote_no}（類似度 {top.score}）</b>：{top.note}</span></div>}
      </div>
    </motion.div>
  )
}
