import { useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, Check, FileSearch, Minus, RefreshCw, Sparkles, Thermometer, TriangleAlert, Undo2, X } from 'lucide-react'
import { api } from '../api'
import { useAi } from '../App'
import type { Fit, PlacedItem } from '../types'
import { Badge, CountUp, Hanko, Progress, dt, fadeUp, num, pct, stagger, useToast, yen } from '../ui'
import type { Ctx } from './ProjectPage'
import FitDecision from './FitDecision'
import { SimilarSizes } from './SimilarCases'

const CAT_COLOR: Record<string, string> = {
  駆動機器: '#4f6ef7', 遮断器: '#ec7a3c', 開閉器: '#f1b434', 制御機器: '#8a6ce0', 電源: '#e05a73',
  端子台: '#93a1b5', 付属品: '#2fb59a', 保護機器: '#c4568f', 扉面機器: '#4f6ef7', 放熱機器: '#2fb59a',
}
const color = (c: string) => CAT_COLOR[c] || '#7a8aa0'

type Tip = { x: number; y: number; it: PlacedItem } | null

function LayoutSvg({ fit, maxOcc, onTip }: { fit: Fit; maxOcc: number; onTip: (t: Tip) => void }) {
  const p = fit.plate!
  const d = fit.door
  const H = Math.max(p.plate_h, p.used_h, d?.door_h ?? 0)
  const gap = 260
  const doorX = p.plate_w + gap
  const W = doorX + (d?.door_w ?? 0)
  const over = p.used_h > p.plate_h
  const fs = 30
  const label = (it: PlacedItem) => it.model.replace('PLC-', '')
  // 箱に収まる文字サイズを求め、小さすぎる場合はラベルを省略する（ツールチップで確認できる）
  const fit1 = (it: PlacedItem, text: string) => Math.min(fs, (it.w - 10) / (text.length * 0.62), it.h * 0.5)
  return (
    <svg viewBox={`-110 -70 ${W + 170} ${H + 130}`} style={{ width: '100%', maxHeight: 740 }} onMouseLeave={() => onTip(null)} data-testid="layout-svg">
      <defs>
        <pattern id="duct" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="12" height="12" fill="#dfe4f2" /><line x1="0" y1="0" x2="0" y2="12" stroke="#c6cde4" strokeWidth="5" />
        </pattern>
        <pattern id="over" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="18" height="18" fill="#ffe1db" /><line x1="0" y1="0" x2="0" y2="18" stroke="#f4a597" strokeWidth="7" />
        </pattern>
        <linearGradient id="plateBg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#f2f4fb" /></linearGradient>
      </defs>

      <text x={p.plate_w / 2} y={-26} textAnchor="middle" fontSize={fs + 4} fill="#1e2a78" fontWeight="800">取付板（有効 W{p.plate_w}×H{p.plate_h}）</text>
      {over && (
        <motion.rect x={0} y={p.plate_h} width={p.plate_w} height={p.used_h - p.plate_h} fill="url(#over)" stroke="#d63a2b" strokeDasharray="12 8" strokeWidth="3"
          animate={{ opacity: [0.55, 1, 0.55] }} transition={{ duration: 1.6, repeat: Infinity }} />
      )}
      <rect x={0} y={0} width={p.plate_w} height={p.plate_h} fill="url(#plateBg)" stroke="#1e2a78" strokeWidth="4" rx="6" />
      {p.ducts.map((dd, i) => <rect key={i} x={dd.x} y={dd.y} width={dd.w} height={Math.min(dd.h, H - dd.y)} fill="url(#duct)" />)}
      {p.items.map((it, i) => (
        <motion.g key={`${it.key}-${i}`} onMouseMove={(e) => onTip({ x: e.clientX, y: e.clientY, it })}
          initial={{ opacity: 0, y: -120 }} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 220, damping: 18, delay: 0.15 + i * 0.022 }}>
          {it.clearance && <rect x={it.fx} y={it.fy} width={it.fw} height={it.fh} fill={color(it.category)} fillOpacity="0.08" stroke={color(it.category)} strokeOpacity="0.7" strokeDasharray="10 7" strokeWidth="2.5" rx="5" />}
          <rect x={it.x} y={it.y} width={it.w} height={it.h} fill={color(it.category)} fillOpacity="0.92" stroke="#fff" strokeWidth="2.5" rx="5" />
          {fit1(it, label(it)) >= 15 && (
            <text x={it.x + it.w / 2} y={it.y + it.h / 2} textAnchor="middle" dominantBaseline="central" fontSize={fit1(it, label(it))} fill="#fff" fontWeight="800" pointerEvents="none">{label(it)}</text>
          )}
        </motion.g>
      ))}
      <line x1={-20} x2={p.plate_w + 20} y1={p.plate_h * maxOcc} y2={p.plate_h * maxOcc} stroke="#b86e00" strokeWidth="4" strokeDasharray="16 10" />
      <text x={p.plate_w + 28} y={p.plate_h * maxOcc} dominantBaseline="central" fontSize={fs - 2} fill="#b86e00" fontWeight="800">{pct(maxOcc, 0)}</text>
      <motion.line x1={-40} x2={-40} y1={0} y2={p.used_h} stroke={over ? '#d63a2b' : '#0c8f62'} strokeWidth="6"
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.2, delay: 0.3 }} />
      <text x={-62} y={p.used_h / 2} fontSize={fs} fill={over ? '#d63a2b' : '#0c8f62'} fontWeight="800" textAnchor="middle" transform={`rotate(-90 -62 ${p.used_h / 2})`}>必要高さ {p.used_h}mm</text>
      {over && <text x={p.plate_w / 2} y={(p.plate_h + p.used_h) / 2} dominantBaseline="central" textAnchor="middle" fontSize={fs + 6} fill="#d63a2b" fontWeight="900">はみ出し {p.used_h - p.plate_h}mm</text>}

      {d && (
        <g transform={`translate(${doorX} 0)`}>
          <text x={d.door_w / 2} y={-26} textAnchor="middle" fontSize={fs + 4} fill="#1e2a78" fontWeight="800">扉面（W{d.door_w}×H{d.door_h}）</text>
          <rect x={0} y={0} width={d.door_w} height={d.door_h} fill="#eef1fa" stroke="#1e2a78" strokeWidth="4" rx="10" />
          <rect x={d.door_w - 60} y={d.door_h / 2 - 90} width={22} height={180} rx="11" fill="#b9c2db" />
          {d.items.map((it, i) => (
            <motion.g key={`${it.key}-${i}`} onMouseMove={(e) => onTip({ x: e.clientX, y: e.clientY, it })}
              initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: 1, scale: 1 }} transition={{ type: 'spring', stiffness: 260, damping: 16, delay: 0.5 + i * 0.03 }}
              style={{ transformOrigin: `${it.x + it.w / 2}px ${it.y + it.h / 2}px`, transformBox: 'fill-box' }}>
              <rect x={it.x} y={it.y} width={it.w} height={it.h} fill={it.recommended ? '#ffffff' : color(it.category)} fillOpacity={it.recommended ? 1 : 0.9}
                stroke={it.recommended ? '#0b8a8f' : '#fff'} strokeDasharray={it.recommended ? '12 8' : undefined} strokeWidth={it.recommended ? 4 : 2.5} rx={it.w <= 40 ? it.w / 2 : 6} />
              {fit1(it, it.recommended ? 'FAN（推奨）' : label(it)) >= 15 && (
                <text x={it.x + it.w / 2} y={it.y + it.h / 2} textAnchor="middle" dominantBaseline="central" fontSize={fit1(it, it.recommended ? 'FAN（推奨）' : label(it))} fill={it.recommended ? '#0b8a8f' : '#fff'} fontWeight="800" pointerEvents="none">
                  {it.recommended ? 'FAN（推奨）' : label(it)}
                </text>
              )}
            </motion.g>
          ))}
        </g>
      )}
    </svg>
  )
}

const CHECK_ICON = {
  ok: { bg: 'var(--grad-ok)', icon: <Check size={14} /> },
  ng: { bg: 'var(--grad-shu)', icon: <X size={14} /> },
  warn: { bg: 'linear-gradient(120deg,#f5b740,#d18a00)', icon: <TriangleAlert size={13} /> },
  na: { bg: '#9aa3c4', icon: <Minus size={14} /> },
}
const SEV = {
  high: { kanji: '重', bg: 'var(--grad-shu)', label: '重要' },
  medium: { kanji: '中', bg: 'linear-gradient(120deg,#f5b740,#d18a00)', label: '注意' },
  low: { kanji: '軽', bg: 'linear-gradient(120deg,#6d84ff,#3d55e6)', label: '参考' },
}

function AiReviewCard({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const { ai } = useAi()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const r = project.ai_review
  const a = project.analysis!
  const stale = r && r.analyzed_at !== a.analyzed_at
  const run = async () => {
    setBusy(true)
    if (await act(() => api.aiReview(project.id))) toast('AI 設計レビューが完了しました', 'success')
    setBusy(false)
  }
  const jump = (key: string) => {
    if (!key) return
    if (a.components.some((c) => c.key === key)) ctx.go('review', { kind: 'component', key })
    else if (a.fields.some((f) => f.key === key)) ctx.go('review', { kind: 'field', key })
  }
  return (
    <motion.div className="card ai-card" variants={fadeUp} data-testid="ai-review">
      <div className="card-head">
        <h3><Sparkles size={16} color="#b14dff" /><span className="magic-text">AI 設計レビュー</span></h3>
        <span className="small muted">ベテラン設計者の観点で、容量・保護協調・放熱・見積漏れを確認します</span>
        <span className="spacer" />
        {r && !busy && <span className="xs muted">{r.usage.model} ・ {r.usage.seconds}秒 ・ {dt(r.at)}</span>}
        <button className="btn btn-sm btn-magic" onClick={run} disabled={busy || !ai.enabled}>
          {r ? <RefreshCw size={14} /> : <Sparkles size={14} />}{busy ? 'レビュー中…' : r ? '再レビュー' : 'AI レビューを実行'}
        </button>
      </div>
      {!ai.enabled && <div className="card-body small muted">AI が接続されていないため利用できません（マスタ・設定 → AI 設定）。</div>}
      {busy && (
        <div className="thinking">
          <div className="thinking-orb" />
          <div className="bold">構成機器・判定結果・見積条件を総合的に確認しています…</div>
          <div className="small muted mt-4">{ai.review_model} が推論中（通常 20〜40 秒）</div>
        </div>
      )}
      {!busy && r && (
        <>
          {stale && <div className="banner banner-amber" style={{ margin: '12px 20px 0' }}><RefreshCw size={14} />レビュー後に解析内容が変わっています。必要に応じて再レビューしてください。</div>}
          <div className="card-body" style={{ paddingBottom: 6 }}><div className="banner banner-ai"><Sparkles size={16} /><span className="grow">{r.summary}</span></div></div>
          <motion.div variants={stagger} initial="hidden" animate="show">
            {r.findings.map((f, i) => (
              <motion.div key={i} variants={fadeUp} className="finding">
                <div className="finding-sev" style={{ background: SEV[f.severity].bg }} title={SEV[f.severity].label}>{SEV[f.severity].kanji}</div>
                <div>
                  <div className="row-wrap"><span className="bold head">{f.title}</span><Badge cls="badge-outline">{f.category}</Badge>
                    {f.target_key && <button className="chip" onClick={() => jump(f.target_key)}><FileSearch size={11} />該当箇所を見る</button>}</div>
                  <div className="small text-2 mt-4">{f.detail}</div>
                </div>
              </motion.div>
            ))}
          </motion.div>
          <div className="card-foot xs muted">AI による参考所見です。採否は設計担当者が判断してください。</div>
        </>
      )}
      {!busy && !r && ai.enabled && <div className="card-body small text-2">「AI レビューを実行」を押すと、11kW 化に伴う遮断器容量など、判定ルールだけでは拾いにくい観点を指摘します。</div>}
    </motion.div>
  )
}

export default function FitTab({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const a = project.analysis!
  const fit = a.fit
  const [tip, setTip] = useState<Tip>(null)
  const enc = fit.enclosure
  const reserve = fit.checks.find((c) => c.id === 'reserve')
  const maxOcc = reserve?.limit ?? 0.85
  const th = fit.thermal
  const includeFan = project.settings?.include_fan ?? true
  const V = {
    ok: { title: '収容可', sub: 'すべてのチェック項目を満たしています', seal: '可', color: '#0c8f62' },
    ng: { title: '収容不可', sub: `${fit.checks.filter((c) => c.status === 'ng').map((c) => c.label).join('・')}を満たしません`, seal: '不可', color: '#d63a2b' },
    insufficient: { title: '情報不足', sub: '判定に必要な寸法データが不足しています', seal: '保留', color: '#b86e00' },
  }[fit.verdict]
  const setEnc = async (id: string | null) => {
    if (await act(() => api.settings(project.id, { enclosure_id: id }), id ? '筐体を変更して再判定しました' : '仕様書指定の筐体に戻しました')) {
      document.querySelector('.page')?.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }
  const cats = Array.from(new Set([...(fit.plate?.items || []), ...(fit.door?.items || []).filter((i) => !i.recommended)].map((i) => i.category)))
  const encKey = `${enc?.id ?? enc?.name}-${fit.verdict}`

  return (
    <div className="page">
      <motion.div className="page-narrow col gap-20" variants={stagger} initial="hidden" animate="show">
        <motion.div className={`verdict ${fit.verdict}`} variants={fadeUp} key={encKey} data-testid="verdict">
          <motion.div initial={{ scale: 2.6, rotate: -35, opacity: 0 }} animate={{ scale: 1, rotate: -12, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 13, delay: 0.25 }}>
            <Hanko text={V.seal} size={92} color={V.color} />
          </motion.div>
          <div className="grow">
            <div className="small muted bold">収容判定（{enc?.name || '筐体未確定'}{enc?.from_spec ? '・仕様書指定' : enc ? '・代替案を採用中' : ''}）</div>
            <div className="verdict-title" style={{ color: V.color }}>{V.title}</div>
            <div className="text-2">{V.sub}</div>
          </div>
          {fit.plate && (
            <div style={{ width: 300 }}>
              <div className="row small"><span className="grow text-2 bold">取付板の使用率</span>
                <b className="num head" style={{ fontSize: 22, color: fit.plate.occupancy > maxOcc ? 'var(--danger)' : 'var(--ok)' }}>
                  <CountUp value={Math.round(fit.plate.occupancy * 1000)} format={(n) => `${(n / 10).toFixed(1)}%`} /></b></div>
              <div className="mt-8"><Progress value={fit.plate.occupancy} limit={maxOcc} color={fit.plate.occupancy > maxOcc ? 'var(--grad-shu)' : 'var(--grad-ok)'} /></div>
              <div className="xs muted mt-8">上限 {pct(maxOcc, 0)}（{reserve?.rule}）</div>
            </div>
          )}
        </motion.div>

        {fit.spec_result && fit.spec_enclosure && enc && (
          <motion.div className="compare" variants={fadeUp}>
            <div className="compare-box">
              <div className="xs muted bold">仕様書指定</div>
              <div className="row mt-4"><b className="head">{fit.spec_enclosure.name}</b><Badge cls={fit.spec_result.verdict === 'ok' ? 'badge-green' : 'badge-red'}>{fit.spec_result.verdict === 'ok' ? '可' : '不可'}</Badge></div>
              <div className="small text-2">必要高さ {fit.spec_result.used_h}mm / 有効 {fit.spec_result.plate_h}mm（使用率 {pct(fit.spec_result.occupancy)}）</div>
            </div>
            <motion.div animate={{ x: [0, 6, 0] }} transition={{ duration: 1.4, repeat: Infinity }}><ArrowRight size={24} color="var(--ai-500)" /></motion.div>
            <div className="compare-box" style={{ borderColor: 'var(--ai-400)', background: 'linear-gradient(120deg, var(--ai-50), #fff)' }}>
              <div className="xs bold" style={{ color: 'var(--ai-600)' }}>採用中の代替案</div>
              <div className="row mt-4"><b className="head">{enc.name}</b><Badge cls={fit.verdict === 'ok' ? 'badge-green' : 'badge-red'}>{fit.verdict === 'ok' ? '可' : '不可'}</Badge>
                <span className="spacer" /><button className="btn btn-xs" onClick={() => setEnc(null)}><Undo2 size={12} />仕様書指定に戻す</button></div>
              <div className="small text-2">必要高さ {fit.plate?.used_h}mm / 有効 {fit.plate?.plate_h}mm（使用率 {pct(fit.plate?.occupancy)}）・ 質疑書に寸法変更の提案を自動追加済み</div>
            </div>
          </motion.div>
        )}

        <AiReviewCard ctx={ctx} />

        <div className="two-col" style={{ '--side': '450px', gap: 20 } as React.CSSProperties}>
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head">
              <h3>配置シミュレーション</h3>
              <span className="spacer" />
              {fit.plate && <span className="small muted">{fit.plate.rows.length} 段 ・ 横ダクト {fit.plate.n_horizontal_ducts} 本</span>}
            </div>
            <div className="card-body">
              {fit.plate ? (
                <>
                  <div className="svg-wrap" key={encKey}><LayoutSvg fit={fit} maxOcc={maxOcc} onTip={setTip} /></div>
                  <div className="legend mt-12">
                    {cats.map((c) => <span key={c}><i style={{ background: color(c) }} />{c}</span>)}
                    <span><i style={{ background: '#dfe4f2' }} />配線ダクト</span>
                    <span><i style={{ border: '1.5px dashed #4f6ef7', background: 'transparent' }} />放熱クリアランス</span>
                    <span><i style={{ background: 'transparent', borderTop: '2px dashed #b86e00', borderRadius: 0, height: 0, width: 16 }} />予備スペース確保ライン</span>
                    {fit.door?.items.some((i) => i.recommended) && <span><i style={{ border: '2px dashed #0b8a8f', background: '#fff' }} />推奨ファン</span>}
                  </div>
                  <div className="xs muted mt-8">機器は高さ順に段へ詰め、段間に配線ダクトを配置する簡易モデルです。配置は判定根拠の可視化を目的とし、製作図ではありません。</div>
                </>
              ) : <div className="empty">外形寸法が確定すると配置を表示します</div>}
            </div>
          </motion.div>

          <div className="col gap-20">
            <FitDecision ctx={ctx} />
            <motion.div className="card" variants={fadeUp}>
              <div className="card-head"><h3>判定根拠</h3><span className="spacer" /><span className="small muted">{fit.checks.length} 項目</span></div>
              <motion.div variants={stagger} initial="hidden" animate="show">
                {fit.checks.map((c) => (
                  <motion.div key={c.id} className="check" variants={fadeUp}>
                    <div className="check-icon" style={{ background: CHECK_ICON[c.status].bg }}>{CHECK_ICON[c.status].icon}</div>
                    <div>
                      <div className="bold">{c.label}</div>
                      <div className="small text-2">{c.detail}</div>
                      {c.rule && <div className="xs muted mt-4">適用ルール：{c.rule}</div>}
                    </div>
                  </motion.div>
                ))}
              </motion.div>
            </motion.div>

            <motion.div className="card" variants={fadeUp}>
              <div className="card-head"><h3>代替筐体の候補</h3><span className="spacer" /><span className="small muted">収容可・設置制限内・安価な順</span></div>
              <div className="card-body col gap-8">
                {fit.alternatives.length === 0 && <div className="small muted">条件を満たす標準筐体がありません。特注筐体または2面構成の検討が必要です。</div>}
                {fit.alternatives.map((alt) => {
                  const current = enc?.id === alt.id
                  return (
                    <div key={alt.id} className={`alt ${current ? 'current' : ''}`}>
                      <div className="grow">
                        <div className="bold head">{alt.name}</div>
                        <div className="small text-2">使用率 {pct(alt.occupancy)} ・ 筐体 {yen(alt.price)}</div>
                      </div>
                      {current ? <Badge cls="badge-blue"><Check size={12} />{enc?.from_spec ? '仕様書指定' : '採用中'}</Badge>
                        : <button className="btn btn-sm btn-primary" onClick={() => setEnc(alt.id)}>この筐体で見積る</button>}
                    </div>
                  )
                })}
              </div>
            </motion.div>

            <SimilarSizes project={project} />

            {th && (
              <motion.div className="card" variants={fadeUp}>
                <div className="card-head"><Thermometer size={17} color={th.need_fan ? 'var(--shu-500)' : 'var(--ok)'} /><h3>盤内温度上昇（概算）</h3></div>
                <div className="card-body">
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    <div><div className="xs muted">発熱量合計</div><div className="bold num head" style={{ fontSize: 19 }}><CountUp value={th.heat_w} /> W</div></div>
                    <div><div className="xs muted">有効放熱面積</div><div className="bold num head" style={{ fontSize: 19 }}>{th.area_m2} m²</div></div>
                    <div><div className="xs muted">温度上昇</div><div className="bold num head" style={{ fontSize: 19, color: th.need_fan ? 'var(--danger)' : 'var(--ok)' }}>{th.dt} K</div></div>
                  </div>
                  <div className="small text-2 mt-12">
                    周囲 {th.ambient}℃{th.ambient_from_spec ? '（仕様書）' : '（既定値）'} → 盤内 <b>{th.internal_temp}℃</b>（上限 {th.max_internal}℃・許容上昇 {th.allow_dt}K）
                  </div>
                  <div className="col gap-4 mt-12">
                    <div className="formula">{th.formula_area}</div>
                    <div className="formula">{th.formula_dt}<span style={{ marginLeft: 12 }}>k = {th.k} W/m²K</span></div>
                    {th.need_fan && <div className="formula">{th.formula_airflow} = {num(th.required_airflow)} m³/h</div>}
                  </div>
                  {th.need_fan && th.fan && (
                    <div className="banner banner-amber mt-12" style={{ alignItems: 'flex-start' }}>
                      <TriangleAlert size={16} style={{ marginTop: 2 }} />
                      <div className="grow">
                        <div className="bold">換気ファン {th.fan.model}（{th.fan.airflow} m³/h）を推奨</div>
                        <div className="small">仕様書の特記事項「必要に応じて換気ファンを設けること」に該当します。</div>
                        <label className="row small mt-8">
                          <input type="checkbox" checked={includeFan} onChange={(e) => act(() => api.settings(project.id, { include_fan: e.target.checked }), e.target.checked ? '推奨ファンを見積に含めました' : '推奨ファンを見積から外しました')} />
                          推奨ファンを構成機器・見積に含める
                        </label>
                      </div>
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </div>
        </div>
      </motion.div>
      {tip && (
        <div className="tooltip" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          <div className="bold">{tip.it.name}</div>
          <div className="mono">{tip.it.model}</div>
          <div>W{tip.it.w} × H{tip.it.h} mm{tip.it.clearance ? `（クリアランス込み ${tip.it.fw}×${tip.it.fh}）` : ''}</div>
          {tip.it.recommended && <div>放熱計算による推奨品</div>}
        </div>
      )}
    </div>
  )
}
