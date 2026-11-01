import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Copy, Globe2, Info, PackageSearch, Undo2 } from 'lucide-react'
import { api } from '../api'
import type { EstimateLine } from '../types'
import { CountUp, fadeUp, num, pct, stagger, useToast, yen } from '../ui'
import type { Ctx } from './ProjectPage'
import { SimilarCard } from './SimilarCases'

function EditCell({ value, onSave, format, width = 70, label }: { value: number | null; onSave: (v: number) => void; format: (v: number | null) => string; width?: number; label: string }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(String(value ?? ''))
  useEffect(() => setV(String(value ?? '')), [value])
  if (!editing) return <span className="edit-cell num" role="button" tabIndex={0} title="クリックして修正" aria-label={`${label}を修正`} onClick={() => setEditing(true)} onKeyDown={(e) => e.key === 'Enter' && setEditing(true)}>{format(value)}</span>
  const commit = () => {
    setEditing(false)
    const n = Number(v)
    if (v.trim() !== '' && !isNaN(n) && n !== value) onSave(n)
  }
  return (
    <input className="input input-sm num right" style={{ width }} autoFocus value={v} aria-label={label} onChange={(e) => setV(e.target.value)}
      onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setV(String(value ?? '')); setEditing(false) } }} />
  )
}

const FLAG = {
  rfq: { label: '要見積依頼', bg: 'var(--danger-soft)', color: 'var(--danger)' },
  expired: { label: '単価期限切れ', bg: 'var(--warn-soft)', color: 'var(--warn)' },
  edited: { label: '修正済', bg: 'var(--ok-soft)', color: 'var(--ok)' },
  market: { label: '市況係数', bg: 'var(--ai-50)', color: 'var(--ai-600)' },
} as Record<string, { label: string; bg: string; color: string }>

/** 原価構成の色。カテゴリの順序は固定（検証済みパレット：CVD 隣接ΔE 9.1 以上）。 */
const GROUP_COLOR: Record<string, string> = {
  enclosure: '#3d55e6', equipment: '#eb6834', spares: '#1baf7a', materials: '#eda100', labor: '#e87ba4', expenses: '#6250d6',
}

function CostComposition({ groups, total }: { groups: { gid: string; name: string; cost: number }[]; total: number }) {
  const [tip, setTip] = useState<{ x: number; y: number; g: { name: string; cost: number } } | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  return (
    <div>
      <div className="stack-bar" onMouseLeave={() => { setTip(null); setHover(null) }} role="img" aria-label="原価構成">
        {groups.map((g, i) => (
          <motion.div key={g.gid} initial={{ width: 0 }} animate={{ width: `${(g.cost / total) * 100}%` }} transition={{ duration: 0.9, delay: 0.1 + i * 0.08, ease: [0.2, 0.8, 0.2, 1] }}
            style={{ background: GROUP_COLOR[g.gid], opacity: hover && hover !== g.gid ? 0.35 : 1 }}
            onMouseMove={(e) => { setTip({ x: e.clientX, y: e.clientY, g }); setHover(g.gid) }} />
        ))}
      </div>
      <div className="stack-legend">
        {groups.map((g) => (
          <div key={g.gid} style={{ display: 'contents' }} onMouseEnter={() => setHover(g.gid)} onMouseLeave={() => setHover(null)}>
            <span style={{ opacity: hover && hover !== g.gid ? 0.5 : 1 }}><i className="sw" style={{ background: GROUP_COLOR[g.gid] }} />{g.name}</span>
            <span className="num right bold">{yen(g.cost)}</span>
            <span className="num right muted">{pct(g.cost / total)}</span>
          </div>
        ))}
      </div>
      {tip && <div className="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}><b>{tip.g.name}</b><div className="num">{yen(tip.g.cost)}（{pct(tip.g.cost / total)}）</div></div>}
    </div>
  )
}

export default function EstimateTab({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const toast = useToast()
  const est = project.analysis!.estimate
  const [margin, setMargin] = useState(est.margin)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => setMargin(est.margin), [est.margin])

  const changeMargin = (m: number) => {
    setMargin(m)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => act(() => api.settings(project.id, { margin: m })), 350)
  }
  const edit = (l: EstimateLine, b: { qty?: number; unit_cost?: number }) => act(() => api.lineEdit(project.id, l.id, b), `${l.name}を修正しました`)

  const groups = Object.entries(est.groups).map(([gid, name]) => ({ gid, name, lines: est.lines.filter((l) => l.group === gid) })).filter((g) => g.lines.length)
  const comp = groups.map((g) => ({ gid: g.gid, name: g.name, cost: g.lines.reduce((s, l) => s + l.cost, 0) })).filter((g) => g.cost > 0)
  const previewSale = Math.floor(est.cost_total / (1 - margin) / 10000) * 10000
  const dragging = Math.abs(margin - est.margin) > 0.0001
  const sale = dragging ? previewSale : est.sale_total
  const profit = sale - est.cost_total
  const tax = dragging ? Math.floor(sale * est.tax_rate) : est.tax
  const rfq = [...est.rfq, ...est.expired]
  const mk = est.market
  const marketOn = !!mk && (Math.abs(mk.steel - 1) > 1e-6 || Math.abs(mk.fx - 1) > 1e-6)

  const copyRfq = async () => {
    const text = rfq.map((l) => `${l.name}\t${l.spec}\t${l.qty}${l.unit}\t${l.flags.includes('expired') ? '単価更新依頼' : '新規見積依頼'}`).join('\n')
    try {
      await navigator.clipboard.writeText(`品名\t型式\t数量\t依頼内容\n${text}`)
      toast('見積依頼リストをコピーしました（Excel に貼り付け可能）', 'success')
    } catch {
      toast('クリップボードにコピーできませんでした', 'error')
    }
  }

  return (
    <div className="page">
      <motion.div className="page-narrow two-col" style={{ '--side': '360px' } as React.CSSProperties} variants={stagger} initial="hidden" animate="show">
        <div className="col gap-20">
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>原価構成</h3><span className="spacer" /><span className="small muted">原価合計 {yen(est.cost_total)}</span></div>
            <div className="card-body"><CostComposition groups={comp} total={est.cost_total} /></div>
          </motion.div>
          <SimilarCard project={project} />
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head">
              <h3>原価明細（社内用）</h3>
              <span className="spacer" />
              <span className="small muted row gap-4"><Info size={13} />数量・単価はクリックで修正できます</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="table" style={{ fontSize: 12.5 }}>
                <thead><tr><th>名称</th><th>仕様・型式</th><th className="right">数量</th><th>単位</th><th className="right">単価</th><th className="right">金額</th><th>根拠</th></tr></thead>
                <tbody>
                  {groups.map((g) => [
                    <tr key={g.gid} className="group-row"><td colSpan={5}><i className="sw" style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, background: GROUP_COLOR[g.gid], marginRight: 8 }} />{g.name}</td>
                      <td className="right num">{yen(g.lines.reduce((s, l) => s + l.cost, 0))}</td><td /></tr>,
                    ...g.lines.map((l) => (
                      <tr key={l.id}>
                        <td>
                          <span className="bold">{l.name}</span>
                          {l.flags.map((f) => FLAG[f] && <span key={f} className="flag" style={{ background: FLAG[f].bg, color: FLAG[f].color }}>{FLAG[f].label}</span>)}
                          {l.note && <div className="xs muted">{l.note}</div>}
                        </td>
                        <td className="small mono">{l.spec}{l.base_unit_cost != null && <div className="xs muted" style={{ fontFamily: 'inherit' }}>マスタ単価 {yen(l.base_unit_cost)}</div>}</td>
                        <td className="right">{l.id === 'overhead' ? <span className="num">{num(l.qty, 1)}</span> : <EditCell label={`${l.name}の数量`} value={l.qty} format={(v) => num(v, 1)} onSave={(v) => edit(l, { qty: v })} width={60} />}</td>
                        <td className="small">{l.unit}</td>
                        <td className="right">{l.id === 'overhead' ? <span className="num">{yen(l.unit_cost)}</span> : <EditCell label={`${l.name}の単価`} value={l.unit_cost} format={(v) => (v == null ? '未登録' : yen(v))} onSave={(v) => edit(l, { unit_cost: v })} width={90} />}</td>
                        <td className="right num bold">{yen(l.cost)}</td>
                        <td className="small text-2 nowrap">
                          {l.source}
                          {l.flags.includes('edited') && <button className="btn btn-ghost btn-xs" title="元に戻す" aria-label={`${l.name}を元に戻す`} onClick={() => act(() => api.lineReset(project.id, l.id), '自動計算の値に戻しました')}><Undo2 size={12} /></button>}
                        </td>
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          </motion.div>
        </div>

        <div className="col gap-20" style={{ position: 'sticky', top: 0 }}>
          <motion.div className="price-hero" variants={fadeUp} data-testid="price-hero">
            <div className="xs" style={{ color: 'var(--kin-300)', letterSpacing: '0.16em', fontWeight: 800 }}>御見積金額（税込）</div>
            <div className="v num"><CountUp value={sale + tax} format={yen} /></div>
            <div className="small" style={{ color: '#d4daf5' }}>税抜 {yen(sale)} ・ 消費税 {yen(tax)}</div>
          </motion.div>
          <motion.div className="card" variants={fadeUp}>
            <div className="card-body">
              <div className="sum-row"><span className="text-2">原価合計</span><b className="num">{yen(est.cost_total)}</b></div>
              <div className="mt-8">
                <div className="row small"><span className="grow text-2">利益率（売価に対する粗利）</span><b className="num head" style={{ fontSize: 16 }}>{pct(margin)}</b></div>
                <input className="slider" type="range" min={0} max={0.4} step={0.005} value={margin} aria-label="利益率" onChange={(e) => changeMargin(Number(e.target.value))} />
              </div>
              <div className="sum-row"><span className="text-2">売価（{num(10000)}円未満切捨て）</span><b className="num">{yen(sale)}</b></div>
              {!dragging && est.discount !== 0 && <div className="sum-row small"><span className="muted">うち出精値引</span><span className="num muted">{yen(est.discount)}</span></div>}
              <div className="sum-row"><span className="text-2">粗利</span><b className="num" style={{ color: profit >= 0 ? 'var(--ok)' : 'var(--danger)' }}>{yen(profit)}</b></div>
              <div className="sum-row"><span className="text-2">消費税（{pct(est.tax_rate, 0)}）</span><span className="num">{yen(tax)}</span></div>
              <div className="sum-row total"><span>税込合計</span><span className="num">{yen(sale + tax)}</span></div>
            </div>
          </motion.div>

          {marketOn && mk && (
            <motion.div className="card market-card" variants={fadeUp} data-testid="market-card">
              <div className="card-head"><Globe2 size={17} color="var(--ai-500)" /><h3>市況係数を反映中</h3><span className="spacer" />
                <b className="num" style={{ color: mk.delta >= 0 ? 'var(--shu-600, var(--danger))' : 'var(--ok)' }}>{mk.delta >= 0 ? '+' : ''}{yen(mk.delta)}</b></div>
              <div className="card-body col gap-6 small">
                <div className="row"><span className="grow text-2">鋼材指数 {mk.steel_index}（基準 {mk.steel_index_base}）→ 筐体</span><b className="num">×{mk.steel.toFixed(3)}</b></div>
                <div className="row"><span className="grow text-2">為替 {mk.usd_jpy}円/$（基準 {mk.usd_jpy_base}円）→ 輸入品</span><b className="num">×{mk.fx.toFixed(3)}</b></div>
                <div className="xs muted">原価明細の {mk.lines} 行に反映（「市況係数」の印）。係数は マスタ・設定 → 判定・算定ルール で更新します。</div>
              </div>
            </motion.div>
          )}

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>顧客提出用の明細</h3></div>
            <table className="table" style={{ fontSize: 12 }}>
              <tbody>
                {est.customer_lines.map((c) => (
                  <tr key={c.id}><td>{c.name}<div className="xs muted">{c.qty}{c.unit}</div></td><td className="right num bold" style={{ color: c.amount < 0 ? 'var(--danger)' : undefined }}>{yen(c.amount)}</td></tr>
                ))}
              </tbody>
            </table>
            <div className="card-foot xs muted">原価を区分ごとに集約し、利益率を反映した金額です。Excel 見積書にはこの明細が転記されます。</div>
          </motion.div>

          {rfq.length > 0 && (
            <motion.div className="card" variants={fadeUp}>
              <div className="card-head"><PackageSearch size={17} color="var(--shu-500)" /><h3>見積依頼・単価確認</h3><span className="spacer" />
                <button className="btn btn-xs" onClick={copyRfq}><Copy size={12} />リストをコピー</button></div>
              <div className="card-body col gap-8">
                {rfq.map((l) => (
                  <div key={l.id} className="row small">
                    <span className="dot" style={{ background: l.flags.includes('rfq') ? 'var(--danger)' : 'var(--warn)' }} />
                    <span className="grow">{l.name} <span className="mono muted">{l.spec}</span></span>
                    <span className="muted">{l.flags.includes('rfq') ? '単価未登録' : '期限切れ'}</span>
                  </div>
                ))}
                <div className="xs muted">単価を入力すると、この一覧から外れます。</div>
              </div>
            </motion.div>
          )}
        </div>
      </motion.div>
    </div>
  )
}
