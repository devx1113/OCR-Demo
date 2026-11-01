import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle, BadgeCheck, Clock3, Gauge, GitCompareArrows, History, LayoutPanelTop, PencilLine, Play, ScanLine, ShieldCheck,
  Sparkles, Timer, TrendingDown,
} from 'lucide-react'
import { api } from '../api'
import { navigate } from '../App'
import type { AccuracyReport, EffectReport, FitReport, ImpactResult } from '../types'
import { Badge, CountUp, Empty, SegTabs, Spinner, dt, fadeUp, num, stagger, yen } from '../ui'
import { ImpactTable } from './MasterTools'

// 結果の内訳（部分と全体）。並び順を固定し、隣り合う色は色覚多様性の検証を通した組み合わせ
const OUTCOMES = [
  { k: 'auto', label: '自動抽出のまま', color: '#2a78d6' },
  { k: 'confirmed', label: '担当者が確定', color: '#1baf7a' },
  { k: 'corrected', label: '担当者が修正', color: '#eb6834' },
  { k: 'resolved', label: '矛盾を担当者が判断', color: '#6250d6' },
  { k: 'open', label: '確認中', color: '#eda100' },
] as const
const SERIES = '#2a78d6'

const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

type Tip = { x: number; y: number; title: string; lines: string[] } | null

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null
  return (
    <div className="viz-tip" style={{ left: tip.x, top: tip.y }} role="status">
      <b>{tip.title}</b>{tip.lines.map((l) => <div key={l}>{l}</div>)}
    </div>
  )
}

const tipAt = (e: React.MouseEvent, title: string, lines: string[]): Tip => {
  const r = (e.currentTarget as HTMLElement).closest('.card')!.getBoundingClientRect()
  return { x: e.clientX - r.left + 14, y: e.clientY - r.top + 14, title, lines }
}

/** 自動抽出値の行方（担当者がそのまま使ったか、修正したか）を 1 本の帯で示す */
function OutcomeBar({ r }: { r: AccuracyReport }) {
  const [tip, setTip] = useState<Tip>(null)
  const total = OUTCOMES.reduce((t, o) => t + r.fields[o.k], 0)
  return (
    <div className="card viz-card">
      <div className="card-head"><h3>抽出値の行方</h3><span className="spacer" /><span className="small muted">抽出 {total} 件（{r.projects} 案件）</span></div>
      <div className="card-body">
        <div className="viz-stack" onMouseLeave={() => setTip(null)}>
          {OUTCOMES.filter((o) => r.fields[o.k] > 0).map((o, i) => (
            <motion.span key={o.k} className="viz-seg" style={{ flexGrow: r.fields[o.k], background: o.color }}
              initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: 0.15 + i * 0.12, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              onMouseMove={(e) => setTip(tipAt(e, o.label, [`${r.fields[o.k]} 件（${pct(r.fields[o.k] / Math.max(1, total))}）`]))} />
          ))}
        </div>
        <div className="viz-legend">
          {OUTCOMES.map((o) => (
            <span key={o.k}><i style={{ background: o.color }} />{o.label}<b>{r.fields[o.k]}</b><small>{pct(r.fields[o.k] / Math.max(1, total), 0)}</small></span>
          ))}
        </div>
        <div className="xs muted mt-8">「自動抽出のまま」は担当者が修正していない値、「担当者が確定」は担当者が正しいと確認した値です。記載なしを担当者が補った {r.fields.filled} 件は含みません。</div>
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}

/** 読み取り方法ごとの採用率（ルールのみ／AI のみ／両者一致） */
function MethodBars({ r }: { r: AccuracyReport }) {
  const [tip, setTip] = useState<Tip>(null)
  const rows = [...r.by_method].sort((a, b) => ['both', 'rule', 'ai'].indexOf(a.method) - ['both', 'rule', 'ai'].indexOf(b.method))
  return (
    <div className="card viz-card">
      <div className="card-head"><h3>読み取り方法ごとの採用率</h3></div>
      <div className="card-body col gap-12" onMouseLeave={() => setTip(null)}>
        {rows.map((m, i) => (
          <div key={m.method} className="viz-hbar"
            onMouseMove={(e) => setTip(tipAt(e, m.label, [`採用率 ${pct(m.rate)}`, `抽出 ${m.n} 件・修正 ${m.corrected} 件`]))}>
            <span className="viz-hbar-l">{m.method === 'both' && <Sparkles size={12} />}{m.label}</span>
            <span className="viz-hbar-track">
              {m.rate != null && (
                <motion.span className="viz-hbar-fill" style={{ background: SERIES }} initial={{ width: 0 }} animate={{ width: `${m.rate * 100}%` }}
                  transition={{ delay: 0.2 + i * 0.1, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
              )}
            </span>
            <span className="viz-hbar-v">{m.n ? pct(m.rate) : '—'}<small>{m.n} 件</small></span>
          </div>
        ))}
        <div className="xs muted">ルールと AI が独立に同じ値を読んだ項目は、片方だけの読み取りより修正が少なくなる想定です。PoC ではこの差を実資料で確認します。</div>
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}

function AccuracyView() {
  const [r, setR] = useState<AccuracyReport | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.accuracy().then(setR).catch((e) => setErr(e.message)) }, [])

  return (
    <>
        {err && <div className="banner banner-red">{err}</div>}
        {!r && !err && <div className="empty"><Spinner size={24} /></div>}
        {r && r.projects === 0 && (
          <div className="card"><Empty icon={<Gauge size={26} />} title="解析済みの案件がありません">案件を解析し、抽出値を確認・修正すると、ここに精度が表示されます。</Empty></div>
        )}
        {r && r.projects > 0 && (
          <motion.div className="col gap-20" variants={stagger} initial="hidden" animate="show">
            <motion.div className="kpis" variants={fadeUp}>
              <div className="card kpi report-hero">
                <div className="kpi-icon" style={{ background: 'var(--grad-ai)' }}><Gauge size={22} /></div>
                <div className="grow">
                  <div className="kpi-label">自動抽出値の採用率</div>
                  <div className="kpi-value">{r.fields.rate == null ? '—' : <><CountUp value={Math.round(r.fields.rate * 1000)} format={(n) => (n / 10).toFixed(1)} /><small>%</small></>}</div>
                  <div className="kpi-sub">担当者が修正しなかった割合（確認中を除く）</div>
                </div>
              </div>
              <div className="card kpi" style={{ '--kpi-glow': 'rgba(235,104,52,.1)' } as React.CSSProperties}>
                <div className="kpi-icon" style={{ background: 'var(--grad-shu)' }}><PencilLine size={22} /></div>
                <div><div className="kpi-label">担当者が修正した値</div><div className="kpi-value"><CountUp value={r.fields.corrected} /><small> 件</small></div>
                  <div className="kpi-sub">確定 {r.fields.confirmed} 件・確認済み {pct(r.fields.reviewed_rate, 0)}</div></div>
              </div>
              <div className="card kpi" style={{ '--kpi-glow': 'rgba(177,77,255,.1)' } as React.CSSProperties}>
                <div className="kpi-icon" style={{ background: 'var(--grad-magic)' }}><ShieldCheck size={22} /></div>
                <div><div className="kpi-label">AI の根拠照合</div><div className="kpi-value"><CountUp value={r.ai.verified ?? 0} /><small> 件 採用</small></div>
                  <div className="kpi-sub">引用を原文で確認できず除外 {r.ai.rejected ?? 0} 件</div></div>
              </div>
              <div className="card kpi" style={{ '--kpi-glow': 'rgba(12,143,98,.1)' } as React.CSSProperties}>
                <div className="kpi-icon" style={{ background: 'var(--grad-ok)' }}><AlertTriangle size={22} /></div>
                <div><div className="kpi-label">人の目で見落としやすい事項の検知</div>
                  <div className="kpi-value"><CountUp value={(r.detect.conflicts ?? 0) + (r.detect.changes ?? 0) + (r.detect.missing ?? 0) + (r.detect.drawing_mismatch ?? 0)} /><small> 件</small></div>
                  <div className="kpi-sub">矛盾 {r.detect.conflicts ?? 0}・変更 {r.detect.changes ?? 0}・記載なし {r.detect.missing ?? 0}・図面相違 {r.detect.drawing_mismatch ?? 0}</div></div>
              </div>
            </motion.div>

            <motion.div className="two-col" style={{ '--side': '440px' } as React.CSSProperties} variants={fadeUp}>
              <OutcomeBar r={r} />
              <MethodBars r={r} />
            </motion.div>

            <motion.div className="card" variants={fadeUp}>
              <div className="card-head"><h3>項目ごとの精度</h3><span className="spacer" /><span className="small muted">修正が多い項目から表示。ルール・辞書の改善対象を探せます</span></div>
              <table className="table report-table">
                <thead><tr><th>項目</th><th className="right">抽出</th><th className="right">確定</th><th className="right">修正</th><th className="right">確認中</th><th style={{ width: '32%' }}>採用率</th></tr></thead>
                <tbody>
                  {r.by_field.map((f) => (
                    <tr key={f.key}>
                      <td className="bold">{f.label}</td>
                      <td className="right num">{f.projects}</td>
                      <td className="right num">{f.confirmed || ''}</td>
                      <td className="right num">{f.corrected ? <span className="report-bad">{f.corrected}</span> : ''}</td>
                      <td className="right num muted">{f.open + f.resolved || ''}</td>
                      <td>
                        <div className="report-rate">
                          <span className="report-rate-track"><span style={{ width: `${(f.rate ?? 0) * 100}%`, background: SERIES }} /></span>
                          <span className="num">{pct(f.rate, 0)}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </motion.div>

            <motion.div className="two-col" style={{ '--side': '440px' } as React.CSSProperties} variants={fadeUp}>
              <div className="card">
                <div className="card-head"><h3>案件ごとの結果</h3></div>
                <table className="table">
                  <thead><tr><th>見積番号</th><th>案件名</th><th className="right">資料</th><th className="right">抽出</th><th className="right">修正</th><th className="right">採用率</th></tr></thead>
                  <tbody>
                    {r.rows.map((p) => (
                      <tr key={p.id} className="clickable" onClick={() => navigate(`/projects/${p.id}/review`)} title={`解析 ${dt(p.analyzed_at)}`}>
                        <td className="mono nowrap">{p.quote_no}</td>
                        <td className="bold">{p.name}</td>
                        <td className="right num">{p.documents}</td>
                        <td className="right num">{p.extracted}</td>
                        <td className="right num">{p.corrected || ''}</td>
                        <td className="right num bold">{pct(p.rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card">
                <div className="card-head"><h3>構成機器・図面</h3></div>
                <div className="card-body col gap-12">
                  <div className="report-mini"><BadgeCheck size={16} /><span className="grow">構成機器の採用率</span><b className="num">{pct(r.components.rate)}</b></div>
                  <div className="xs muted" style={{ marginTop: -6 }}>自動 {r.components.auto ?? 0}・確定 {r.components.confirmed ?? 0}・修正 {r.components.corrected ?? 0}・対象外 {r.components.deleted ?? 0}・手動追加 {r.components.manual ?? 0}</div>
                  <div className="report-mini"><GitCompareArrows size={16} /><span className="grow">ルール×AI 一致の項目</span><b className="num">{r.ai.agreed ?? 0}</b></div>
                  <div className="report-mini"><Sparkles size={16} /><span className="grow">AI だけが読み取った項目</span><b className="num">{r.ai.ai_only ?? 0}</b></div>
                  <div className="report-mini"><ScanLine size={16} /><span className="grow">AI-OCR で読んだ図面・寸法</span><b className="num">{r.ai.ocr_docs ?? 0} 枚・{r.ai.ocr_dims ?? 0} 寸法</b></div>
                  <div className="banner banner-blue small mt-8" style={{ alignItems: 'flex-start' }}>
                    <Gauge size={16} style={{ flexShrink: 0, marginTop: 2 }} />
                    <span>本開発前の検証（PoC）では、御社の実案件 10〜20 件をこの画面で集計し、項目ごとの採用率と、ルール・AI それぞれの寄与を確認します。</span>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
    </>
  )
}

// ---------- 効果測定（F8） ----------

function EffectView() {
  const [r, setR] = useState<EffectReport | null>(null)
  const [err, setErr] = useState('')
  const [tip, setTip] = useState<Tip>(null)
  useEffect(() => { api.effectReport().then(setR).catch((e) => setErr(e.message)) }, [])
  if (err) return <div className="banner banner-red">{err}</div>
  if (!r) return <div className="empty"><Spinner size={24} /></div>
  if (!r.projects) return <div className="card"><Empty icon={<Timer size={26} />} title="解析済みの案件がありません">案件を登録して解析・承認まで進めると、作業時間の実績が表示されます。</Empty></div>
  const base = r.baseline_hours * 60
  const max = Math.max(base, ...r.rows.map((x) => x.active_min)) * 1.08
  return (
    <motion.div className="col gap-20" variants={stagger} initial="hidden" animate="show">
      <motion.div className="kpis" variants={fadeUp}>
        <div className="card kpi report-hero">
          <div className="kpi-icon" style={{ background: 'var(--grad-ok)' }}><TrendingDown size={22} /></div>
          <div className="grow">
            <div className="kpi-label">見積作成時間の削減率</div>
            <div className="kpi-value">{r.reduction_rate == null ? '—' : <><CountUp value={Math.round(r.reduction_rate * 1000)} format={(n) => (n / 10).toFixed(1)} /><small>%</small></>}</div>
            <div className="kpi-sub">導入前の想定 {num(r.baseline_hours, 1)} 時間／件との比較（承認まで進んだ {r.completed} 件）</div>
          </div>
        </div>
        <div className="card kpi" style={{ '--kpi-glow': 'rgba(42,120,214,.1)' } as React.CSSProperties}>
          <div className="kpi-icon" style={{ background: 'var(--grad-ai)' }}><Clock3 size={22} /></div>
          <div><div className="kpi-label">1 件あたりの作業時間（推定）</div>
            <div className="kpi-value">{r.avg_active_min == null ? '—' : <><CountUp value={Math.round(r.avg_active_min)} /><small> 分</small></>}</div>
            <div className="kpi-sub">受付から承認依頼までの操作履歴から算出</div></div>
        </div>
        <div className="card kpi" style={{ '--kpi-glow': 'rgba(12,143,98,.1)' } as React.CSSProperties}>
          <div className="kpi-icon" style={{ background: 'var(--grad-ok)' }}><Timer size={22} /></div>
          <div><div className="kpi-label">削減できた時間（累計）</div>
            <div className="kpi-value">{r.saved_hours_total == null ? '—' : <><CountUp value={Math.round(r.saved_hours_total * 10)} format={(n) => (n / 10).toFixed(1)} /><small> 時間</small></>}</div>
            <div className="kpi-sub">想定時間 − 実績の合計</div></div>
        </div>
        <div className="card kpi" style={{ '--kpi-glow': 'rgba(235,104,52,.1)' } as React.CSSProperties}>
          <div className="kpi-icon" style={{ background: 'var(--grad-shu)' }}><PencilLine size={22} /></div>
          <div><div className="kpi-label">抽出値の修正率</div>
            <div className="kpi-value">{r.correction_rate == null ? '—' : <>{(r.correction_rate * 100).toFixed(1)}<small>%</small></>}</div>
            <div className="kpi-sub">自動解析 平均 {r.avg_analysis_sec ?? '—'} 秒／件</div></div>
        </div>
      </motion.div>

      <motion.div className="card viz-card" variants={fadeUp}>
        <div className="card-head"><h3>案件ごとの作業時間</h3><span className="spacer" />
          <span className="small muted row gap-4"><i className="eff-key" />導入前の想定 {num(r.baseline_hours, 1)} 時間（マスタ・設定 → 判定・算定ルールで変更）</span></div>
        <div className="card-body col gap-10" onMouseLeave={() => setTip(null)}>
          {r.rows.map((x, i) => (
            <div key={x.id} className="viz-hbar eff-row clickable" onClick={() => navigate(`/projects/${x.id}/history`)}
              onMouseMove={(e) => setTip(tipAt(e, `${x.quote_no} ${x.name}`, [`作業時間（推定） ${num(x.active_min, 0)} 分・操作 ${x.events} 回`,
                x.lead_hours != null ? `受付から承認依頼まで ${num(x.lead_hours, 1)} 時間` : '承認前（作業中）', `抽出値の修正 ${x.corrected} / ${x.fields} 件`]))}>
              <span className="viz-hbar-l"><span className="mono">{x.quote_no}</span>{!x.completed && <Badge cls="badge-gray">作業中</Badge>}</span>
              <span className="viz-hbar-track eff-track">
                <motion.span className="viz-hbar-fill" style={{ background: SERIES, opacity: x.completed ? 1 : 0.45 }} initial={{ width: 0 }}
                  animate={{ width: `${(x.active_min / max) * 100}%` }} transition={{ delay: 0.15 + i * 0.06, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
                <span className="eff-base" style={{ left: `${(base / max) * 100}%` }} />
              </span>
              <span className="viz-hbar-v">{num(x.active_min, 0)} 分<small>{x.saved_hours != null ? `−${num(x.saved_hours, 1)}h` : ''}</small></span>
            </div>
          ))}
          <div className="xs muted">作業時間は操作履歴の時刻から推定しています（{r.idle_minutes} 分以上操作がない間は数えません）。PoC では導入前の実測値を想定時間に設定し、同じ案件で比較します。</div>
        </div>
        <Tooltip tip={tip} />
      </motion.div>
    </motion.div>
  )
}

// ---------- 判定一致率（G4） ----------

const VJA: Record<string, string> = { ok: '可', ng: '不可', insufficient: '判定不能' }

function FitView() {
  const [r, setR] = useState<FitReport | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.fitReport().then(setR).catch((e) => setErr(e.message)) }, [])
  if (err) return <div className="banner banner-red">{err}</div>
  if (!r) return <div className="empty"><Spinner size={24} /></div>
  if (!r.recorded) {
    return <div className="card"><Empty icon={<LayoutPanelTop size={26} />} title="設計者の最終判断がまだ記録されていません">
      各案件の「収容判定」画面で、システムの判定に対する設計者の最終判断（同意・異なる判断）を記録すると、ここに一致率が表示されます。</Empty></div>
  }
  const parts = [
    { k: 'agree', label: '判定どおり', n: r.agree, color: OUTCOMES[0].color },
    { k: 'enc', label: '可否は一致・筐体が異なる', n: r.enclosure_diff, color: OUTCOMES[4].color },
    { k: 'verdict', label: '可否が異なる', n: r.verdict_diff, color: OUTCOMES[2].color },
  ]
  return (
    <motion.div className="col gap-20" variants={stagger} initial="hidden" animate="show">
      <motion.div className="two-col" style={{ '--side': '440px' } as React.CSSProperties} variants={fadeUp}>
        <div className="card viz-card">
          <div className="card-head"><h3>収容判定と設計者の最終判断</h3><span className="spacer" /><span className="small muted">{r.recorded} 件</span></div>
          <div className="card-body">
            <div className="viz-stack">
              {parts.filter((x) => x.n > 0).map((x, i) => (
                <motion.span key={x.k} className="viz-seg" style={{ flexGrow: x.n, background: x.color }} title={`${x.label} ${x.n} 件`}
                  initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ delay: 0.15 + i * 0.12, duration: 0.6 }} />
              ))}
            </div>
            <div className="viz-legend">
              {parts.map((x) => <span key={x.k}><i style={{ background: x.color }} />{x.label}<b>{x.n}</b><small>{pct(x.n / r.recorded, 0)}</small></span>)}
            </div>
          </div>
        </div>
        <div className="card kpi report-hero">
          <div className="kpi-icon" style={{ background: 'var(--grad-ai)' }}><LayoutPanelTop size={22} /></div>
          <div className="grow">
            <div className="kpi-label">判定一致率</div>
            <div className="kpi-value">{r.rate == null ? '—' : <><CountUp value={Math.round(r.rate * 1000)} format={(n) => (n / 10).toFixed(1)} /><small>%</small></>}</div>
            <div className="kpi-sub">収容判定（C3・C4）の実用性の指標。異なった案件の理由を判定ルールの改善に使います</div>
          </div>
        </div>
      </motion.div>
      <motion.div className="card" variants={fadeUp}>
        <div className="card-head"><h3>記録された判断</h3></div>
        <table className="table">
          <thead><tr><th>見積番号</th><th>案件名</th><th>システム</th><th>設計者</th><th>理由</th><th>記録</th></tr></thead>
          <tbody>
            {r.rows.map((x) => (
              <tr key={x.id} className="clickable" onClick={() => navigate(`/projects/${x.id}/fit`)}>
                <td className="mono nowrap">{x.quote_no}</td>
                <td className="bold">{x.name}</td>
                <td className="small">{VJA[x.system_verdict] ?? x.system_verdict}<div className="xs muted">{x.system_enclosure}</div></td>
                <td className="small">
                  {x.decision === 'agree' ? <Badge cls="badge-green">判定どおり</Badge> : <Badge cls="badge-amber">{VJA[x.final_verdict] ?? x.final_verdict}</Badge>}
                  {x.decision !== 'agree' && x.final_enclosure && <div className="xs muted">{x.final_enclosure}</div>}
                </td>
                <td className="small text-2">{x.reason}</td>
                <td className="xs muted nowrap">{x.by}<div>{dt(x.at)}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </motion.div>
    </motion.div>
  )
}

// ---------- 回帰チェック（G3） ----------

function RegressionView() {
  const [r, setR] = useState<ImpactResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const run = () => {
    setBusy(true)
    setErr('')
    api.regression().then(setR).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  return (
    <motion.div className="col gap-20" variants={stagger} initial="hidden" animate="show">
      <motion.div className="card" variants={fadeUp}>
        <div className="card-body row gap-16 regress-head">
          <div className="kpi-icon" style={{ background: 'var(--grad-magic)' }}><History size={22} /></div>
          <div className="grow">
            <div className="bold head">全案件の再処理チェック</div>
            <div className="small text-2">保存されている解析結果と、現在のマスタ・判定ルールで解析し直した結果を比べます。ルール・マスタ・プログラムを更新したあとに、
              過去の案件の判定や金額が意図せず変わっていないかを確かめます（案件は変更しません）。</div>
          </div>
          <button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? <Spinner size={14} /> : <Play size={14} />}チェックを実行</button>
        </div>
      </motion.div>
      {err && <div className="banner banner-red">{err}</div>}
      {r && (
        <motion.div variants={fadeUp} initial="hidden" animate="show" className="col gap-16">
          <div className={`banner ${r.changed ? 'banner-amber' : 'banner-green'}`}>
            {r.changed ? <AlertTriangle size={16} /> : <BadgeCheck size={16} />}
            <span>{r.total} 件を再処理 ・ {r.changed ? <>結果が変わる案件 <b>{r.changed} 件</b>（判定・筐体 {r.verdict_changed} 件、承認済み・承認待ち {r.locked_changed} 件、金額 {r.sale_delta >= 0 ? '+' : ''}{yen(r.sale_delta)}）</> : 'すべての案件で結果は変わりません'}
              {r.skipped > 0 && <span className="muted">（未解析・再解析待ち {r.skipped} 件は対象外）</span>}</span>
          </div>
          {r.changed > 0 && <div className="card"><ImpactTable rows={r.rows.filter((x) => x.changed)} labels={['保存済みの結果', '現在のルール']} /></div>}
        </motion.div>
      )}
    </motion.div>
  )
}

const REPORT_TABS = [
  { id: 'accuracy', label: '抽出精度', icon: Gauge },
  { id: 'effect', label: '効果測定', icon: Timer },
  { id: 'fit', label: '判定一致率', icon: LayoutPanelTop },
  { id: 'regression', label: '回帰チェック', icon: History },
]

export default function ReportPage({ tab = 'accuracy' }: { tab?: string }) {
  return (
    <div className="page">
      <div className="page-narrow">
        <div className="hero">
          <div className="grow">
            <div className="small muted bold" style={{ letterSpacing: '0.08em' }}>ACCURACY &amp; EFFECT REPORT</div>
            <h1 style={{ fontSize: 26 }}>精度・効果レポート</h1>
            <div className="text-2 mt-4">担当者の確定・修正・判断の記録から、自動抽出の精度、作業時間の削減効果、収容判定の一致率を集計します。日々の作業がそのまま評価データになります。</div>
          </div>
        </div>
        <div style={{ width: 'fit-content', marginBottom: 16 }}>
          <SegTabs id="report" value={tab} onChange={(v) => navigate(`/report/${v}`)} items={REPORT_TABS.map((t) => ({ id: t.id, label: <><t.icon size={14} />{t.label}</> }))} />
        </div>
        <motion.div key={tab} variants={fadeUp} initial="hidden" animate="show">
          {tab === 'accuracy' && <AccuracyView />}
          {tab === 'effect' && <EffectView />}
          {tab === 'fit' && <FitView />}
          {tab === 'regression' && <RegressionView />}
        </motion.div>
      </div>
    </div>
  )
}
