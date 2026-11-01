import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Archive, BookOpen, Boxes, Cpu, Globe2, KeyRound, Languages, Lightbulb, PlugZap, Save, Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { api, can } from '../api'
import { navigate, useAi, useUser } from '../App'
import type { AiStatus, Enclosure } from '../types'
import { Badge, SegTabs, Spinner, fadeUp, useToast, yen } from '../ui'
import { ImpactDialog, LearningTab, PastProjectsTab, VersionsButton } from './MasterTools'

type Part = {
  model: string; name: string; category: string; maker: string; spec: string; mount: string
  w: number; h: number; d: number; heat_w: number; price: number | null; price_valid_until: string | null
  clearance?: { top: number; bottom: number; side: number }; airflow?: number; aliases: string[]; imported?: boolean
}
type Rules = Record<string, Record<string, number> | string>
type Dictionary = {
  fields: { key: string; label: string; aliases: string[]; required: boolean; group: string }[]
  component_names: Record<string, string[]>
  risk_keywords: { pattern: string; label: string; impact: string }[]
}

const TABS = [
  { id: 'parts', label: '部品マスタ', icon: Cpu },
  { id: 'enclosures', label: '筐体マスタ', icon: Boxes },
  { id: 'rules', label: '判定・算定ルール', icon: SlidersHorizontal },
  { id: 'dictionary', label: '変換辞書', icon: Languages },
  { id: 'learning', label: '改善候補', icon: Lightbulb },
  { id: 'past', label: '過去案件', icon: Archive },
  { id: 'ai', label: 'AI 設定', icon: Sparkles },
]

const RULE_LABELS: Record<string, { title: string; items: Record<string, [string, string]> }> = {
  layout: { title: '収容判定（配置ルール）', items: {
    side_duct_w: ['縦ダクト幅', 'mm'], row_duct_h: ['段間ダクト高さ', 'mm'], h_gap: ['機器間隔（横）', 'mm'],
    max_occupancy: ['取付板使用率の上限（仕様書に予備スペース指定がない場合）', '比率'], depth_clearance: ['奥行き余裕', 'mm'],
    door_margin: ['扉面の周囲余白', 'mm'], door_gap: ['扉面機器の間隔', 'mm'] } },
  thermal: { title: '温度上昇の概算', items: {
    k: ['熱通過率 k', 'W/m²K'], max_internal: ['盤内許容温度', '℃'], max_internal_temp: ['盤内許容温度', '℃'],
    default_ambient: ['周囲温度（仕様書に記載がない場合）', '℃'], airflow_factor: ['風量係数 f', ''] } },
  labor: { title: '工数算定式', items: {
    rate: ['工数単価', '円/h'], design_base_h: ['設計 基本', 'h'], design_per_type_h: ['設計 機器1種あたり', 'h'],
    assembly_base_h: ['製作 基本', 'h'], assembly_per_unit_h: ['製作 機器1点あたり', 'h'], test_base_h: ['試験 基本', 'h'],
    witness_h: ['立会検査 加算', 'h'], docs_h_per_kind: ['図書作成 1種あたり', 'h'] } },
  cost: { title: '経費・材料単価', items: {
    overhead_rate: ['諸経費率', '比率'], transport: ['運搬費', '円'], default_margin: ['標準利益率', '比率'], round_unit: ['端数処理単位', '円'],
    tax_rate: ['消費税率', '比率'], duct_price_per_m: ['配線ダクト単価', '円/m'], din_price_per_m: ['DINレール単価', '円/m'],
    wire_per_unit: ['電線・端子 機器1点あたり', '円'], nameplate: ['銘板単価', '円/枚'] } },
  market: { title: '市況係数（為替・鋼材）', items: {
    steel_index_base: ['鋼材指数（マスタ単価の登録時点）', ''], steel_index: ['鋼材指数（現在）', ''], steel_share: ['筐体価格のうち鋼材に連動する割合', '比率'],
    usd_jpy_base: ['為替（マスタ単価の登録時点）', '円/$'], usd_jpy: ['為替（現在）', '円/$'], import_share: ['輸入品価格のうち為替に連動する割合', '比率'] } },
  effect: { title: '効果測定の基準', items: {
    baseline_hours: ['導入前の見積作成時間（1件あたり）', 'h'], idle_minutes: ['作業時間に数えない操作の空き', '分'] } },
}

/** 市況係数の計算（サーバーの estimate.market_factors と同じ式。入力中の確認用） */
function marketFactors(m: Record<string, number> | undefined) {
  if (!m) return null
  return {
    steel: 1 + (m.steel_index / m.steel_index_base - 1) * m.steel_share,
    fx: 1 + (m.usd_jpy / m.usd_jpy_base - 1) * m.import_share,
  }
}

function PartsTab() {
  const [parts, setParts] = useState<Part[] | null>(null)
  const [dirty, setDirty] = useState(false)
  const [q, setQ] = useState('')
  const [impact, setImpact] = useState<Part[] | null>(null)
  const user = useUser()
  const load = () => api.master<Part[]>('parts').then((x) => { setParts(x); setDirty(false) })
  useEffect(() => { load() }, [])
  const today = new Date().toISOString().slice(0, 10)
  const list = useMemo(() => (parts || []).filter((p) => !q || `${p.model} ${p.name} ${p.maker} ${p.category}`.toLowerCase().includes(q.toLowerCase())), [parts, q])
  const update = (model: string, patch: Partial<Part>) => {
    setParts((ps) => ps!.map((p) => (p.model === model ? { ...p, ...patch } : p)))
    setDirty(true)
  }
  if (!parts) return <div className="card-body"><Spinner /></div>
  return (
    <>
      <div className="card-head">
        <div className="row" style={{ position: 'relative' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, color: 'var(--muted)' }} />
          <input className="input input-sm" style={{ paddingLeft: 30, width: 260 }} placeholder="型式・品名・メーカーで検索" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <span className="small muted">{list.length} / {parts.length} 件</span>
        <span className="spacer" />
        <VersionsButton name="parts" title="部品マスタ" onRestored={load} />
        <button className="btn btn-sm btn-primary" disabled={!dirty || !can('master', user)} onClick={() => setImpact(parts.map((p) => ({ ...p })))}><Save size={14} />影響を確認して保存</button>
      </div>
      {impact && <ImpactDialog name="parts" title="部品マスタ" data={impact} onClose={() => setImpact(null)} onSaved={() => { setImpact(null); load() }} />}
      <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 250px)' }}>
        <table className="table" style={{ fontSize: 12.5 }}>
          <thead><tr><th>型式</th><th>品名</th><th>区分</th><th>メーカー</th><th>取付</th><th className="right">W×H×D (mm)</th><th className="right">発熱</th><th className="right">単価</th><th>単価有効期限</th></tr></thead>
          <tbody>
            {list.map((p) => {
              const expired = p.price_valid_until && p.price_valid_until < today
              return (
                <tr key={p.model}>
                  <td className="mono bold nowrap">{p.model}</td>
                  <td>{p.name}{p.imported && <span className="flag flag-market" title="為替の市況係数の対象">輸入品</span>}<div className="xs muted">{p.spec}{p.clearance ? ` ・ クリアランス 上下${p.clearance.top}/左右${p.clearance.side}` : ''}{p.airflow ? ` ・ ${p.airflow}m³/h` : ''}</div></td>
                  <td className="small">{p.category}</td>
                  <td className="small">{p.maker}</td>
                  <td className="small">{{ plate: '取付板', door: '扉面', terminal: '端子' }[p.mount]}</td>
                  <td className="right num nowrap">{p.w}×{p.h}×{p.d}</td>
                  <td className="right num">{p.heat_w} W</td>
                  <td className="right">
                    <input className="input input-sm num right" style={{ width: 100, borderColor: p.price == null ? 'var(--danger)' : undefined }} value={p.price ?? ''} placeholder="未登録"
                      onChange={(e) => update(p.model, { price: e.target.value === '' ? null : Number(e.target.value) })} />
                  </td>
                  <td>
                    <input className="input input-sm" type="date" style={{ borderColor: expired ? 'var(--warn)' : undefined }} value={p.price_valid_until || ''}
                      onChange={(e) => update(p.model, { price_valid_until: e.target.value || null })} />
                    {expired && <div className="xs" style={{ color: 'var(--warn)' }}>期限切れ</div>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function EnclosuresTab() {
  const [list, setList] = useState<Enclosure[] | null>(null)
  useEffect(() => { api.master<Enclosure[]>('enclosures').then(setList) }, [])
  if (!list) return <div className="card-body"><Spinner /></div>
  return (
    <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 200px)' }}>
      <table className="table" style={{ fontSize: 12.5 }}>
        <thead><tr><th>ID</th><th>名称</th><th className="right">外形 W×H×D</th><th className="right">取付板 有効</th><th className="right">盤内奥行</th><th className="right">単価</th></tr></thead>
        <tbody>
          {list.map((e) => (
            <tr key={e.id}>
              <td className="mono">{e.id}</td><td>{e.name}</td>
              <td className="right num">{e.w}×{e.h}×{e.d}</td><td className="right num">{e.plate_w}×{e.plate_h}</td>
              <td className="right num">{e.inner_d}</td><td className="right num bold">{yen(e.price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RulesTab() {
  const user = useUser()
  const [rules, setRules] = useState<Rules | null>(null)
  const [dirty, setDirty] = useState(false)
  const [impact, setImpact] = useState<Rules | null>(null)
  const load = () => api.master<Rules>('rules').then((x) => { setRules(x); setDirty(false) })
  useEffect(() => { load() }, [])
  if (!rules) return <div className="card-body"><Spinner /></div>
  const mf = marketFactors(rules.market as Record<string, number> | undefined)
  const set = (g: string, k: string, v: number) => {
    setRules({ ...rules, [g]: { ...(rules[g] as Record<string, number>), [k]: v } })
    setDirty(true)
  }
  return (
    <>
      <div className="card-head">
        <span className="small text-2">設計担当者の判断基準をルールとして明文化し、権限者が更新します。変更は次回の解析・再計算から反映されます。</span>
        <span className="spacer" />
        <VersionsButton name="rules" title="判定・算定ルール" onRestored={load} />
        <button className="btn btn-sm btn-primary" disabled={!dirty || !can('master', user)} onClick={() => setImpact(JSON.parse(JSON.stringify(rules)))} data-testid="rules-save"><Save size={14} />影響を確認して保存</button>
      </div>
      {impact && <ImpactDialog name="rules" title="判定・算定ルール" data={impact} onClose={() => setImpact(null)} onSaved={() => { setImpact(null); load() }} />}
      <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16 }}>
        {Object.entries(RULE_LABELS).map(([g, def]) => (
          <div key={g} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div className="bold mb-8 row gap-6">{g === 'market' && <Globe2 size={15} color="var(--ai-500)" />}{def.title}</div>
            {g === 'market' && mf && (
              <div className="market-preview">
                <span>筐体 <b className="num">×{mf.steel.toFixed(3)}</b></span><span>輸入品 <b className="num">×{mf.fx.toFixed(3)}</b></span>
                <span className="xs muted">マスタ単価に掛けて見積します</span>
              </div>
            )}
            <div className="col gap-8 mt-8">
              {Object.entries((rules[g] ?? {}) as Record<string, number>).map(([k, v]) => (
                <label key={k} className="row small">
                  <span className="grow text-2">{def.items[k]?.[0] || k}</span>
                  <input className="input input-sm num right" style={{ width: 100 }} type="number" step="any" value={v} aria-label={def.items[k]?.[0] || k} onChange={(e) => set(g, k, Number(e.target.value))} />
                  <span className="xs muted" style={{ width: 44 }}>{def.items[k]?.[1]}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
        <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div className="bold">資料間で値が異なる場合の仮採用ルール</div>
          <select className="select mt-8" value={rules.conflict_policy as string} onChange={(e) => { setRules({ ...rules, conflict_policy: e.target.value }); setDirty(true) }}>
            <option value="newer">受領日が新しい資料を仮採用</option>
            <option value="main">主仕様書を仮採用</option>
          </select>
          <div className="xs muted mt-8">いずれの場合も「矛盾」として表示し、担当者の確定または質疑で解決します。</div>
        </div>
      </div>
    </>
  )
}

function DictionaryTab() {
  const [dic, setDic] = useState<Dictionary | null>(null)
  const load = () => api.master<Dictionary>('dictionary').then(setDic)
  useEffect(() => { load() }, [])
  if (!dic) return <div className="card-body"><Spinner /></div>
  return (
    <>
    <div className="card-head">
      <span className="small text-2">資料の表記ゆれを統一する辞書です。担当者の修正から作った「改善候補」を反映すると、ここに追加されます。</span>
      <span className="spacer" />
      <VersionsButton name="dictionary" title="変換辞書" onRestored={load} />
    </div>
    <div className="card-body" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
      <div>
        <div className="section-title">機器名称の統一（{Object.keys(dic.component_names).length}）</div>
        <div className="col gap-8">
          {Object.entries(dic.component_names).map(([k, v]) => (
            <div key={k} className="row-wrap small" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <b style={{ width: 150 }}>{k}</b>{v.map((a) => <span key={a} className="badge badge-outline">{a}</span>)}
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="section-title">抽出項目と項目名の別表記（{dic.fields.length}）</div>
        <div className="col gap-8">
          {dic.fields.map((f) => (
            <div key={f.key} className="row-wrap small" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <b style={{ width: 150 }}>{f.label}{f.required && <span style={{ color: 'var(--danger)' }}> *</span>}</b>
              {f.aliases.map((a) => <span key={a} className="badge badge-outline">{a}</span>)}
            </div>
          ))}
        </div>
        <div className="section-title mt-24">見積漏れリスクの検出語（{dic.risk_keywords.length}）</div>
        {dic.risk_keywords.map((r) => (
          <div key={r.label} className="small" style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <b>{r.label}</b> <span className="mono muted">/{r.pattern}/</span><div className="xs text-2">{r.impact}</div>
          </div>
        ))}
      </div>
    </div>
    </>
  )
}

function AiTab() {
  const toast = useToast()
  const { refreshAi } = useAi()
  const [s, setS] = useState<AiStatus | null>(null)
  const [test, setTest] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.aiSettings().then(setS) }, [])
  if (!s) return <div className="card-body"><Spinner /></div>
  const save = async (patch: Partial<AiStatus>) => {
    const r = await api.saveAiSettings(patch)
    setS(r)
    refreshAi()
    toast('AI 設定を保存しました', 'success')
  }
  const runTest = async () => {
    setBusy(true)
    setTest(null)
    try {
      const r = await api.aiTest()
      setTest(`「${r.reply}」 ・ ${r.usage.model} ・ ${r.usage.seconds}秒`)
    } catch (e) {
      setTest(`失敗：${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 18 }}>
      <div className="col gap-12" style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 18 }}>
        <div className="row"><KeyRound size={18} color="var(--ai-500)" /><b className="head">OpenAI API</b><span className="spacer" />
          <Badge cls={s.configured ? 'badge-green' : 'badge-red'}>{s.configured ? 'API キー設定済み' : 'API キー未設定'}</Badge></div>
        <div className="small text-2">API キーはサーバーの <code>.env</code>（OPENAI_API_KEY）に保存され、画面やブラウザには送られません。</div>
        <label className="row small"><input type="checkbox" checked={s.enabled} disabled={!s.configured} onChange={(e) => save({ enabled: e.target.checked })} />AI 機能を有効にする（無効時はルール抽出のみで動作）</label>
        <div className="row">
          <button className="btn btn-magic btn-sm" onClick={runTest} disabled={busy || !s.enabled}>{busy ? <Spinner size={13} /> : <PlugZap size={14} />}接続テスト</button>
          {test && <span className="small" style={{ color: test.startsWith('失敗') ? 'var(--danger)' : 'var(--ok)' }}>{test}</span>}
        </div>
      </div>
      <div className="col gap-12" style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 18 }}>
        <b className="head">使用するモデル</b>
        <label className="field-group"><span className="label">AI 読解・質問応答・メール文案（速さ重視）</span>
          <select className="select" value={s.model} onChange={(e) => save({ model: e.target.value })}>{(s.models || [s.model]).map((m) => <option key={m}>{m}</option>)}</select></label>
        <label className="field-group"><span className="label">AI 設計レビュー（推論の深さ重視）</span>
          <select className="select" value={s.review_model} onChange={(e) => save({ review_model: e.target.value })}>{(s.models || [s.review_model]).map((m) => <option key={m}>{m}</option>)}</select></label>
        <div className="xs muted">モデルを変えると、次回の AI 読解から反映されます（読解結果は資料・モデルごとにキャッシュ）。</div>
      </div>
      <div className="col gap-8" style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 18, gridColumn: '1 / -1' }}>
        <b className="head">AI の結果を見積に使うときの安全策</b>
        {['AI には資料を「[ID] 本文」の形で渡し、値は原文どおり・根拠の ID と引用付きで返させる',
          '引用が原文に実在し、値の数値が原文と一致するかをプログラムで照合。照合できない値は採用しない',
          'ルール抽出と AI 読解が一致した値は「一致」、AI だけが読んだ値は「要確認」として担当者に返す',
          'AI だけの読み取りがルール抽出と食い違う場合は、承認を止める「矛盾」にせず参考値として表示',
          '設計レビュー・メール文案は参考として提示し、採否・送信は担当者が判断'].map((t) => (
          <div key={t} className="row small" style={{ alignItems: 'flex-start' }}><Sparkles size={13} color="#b14dff" style={{ marginTop: 3 }} />{t}</div>
        ))}
      </div>
    </div>
  )
}

export default function MasterPage({ tab }: { tab: string }) {
  const user = useUser()
  return (
    <div className="page">
      <div className="page-narrow">
        <div className="hero">
          <div className="grow">
            <div className="small muted bold" style={{ letterSpacing: '0.08em' }}>MASTER &amp; RULES</div>
            <h1 style={{ fontSize: 26 }}>マスタ・設定</h1>
            <div className="text-2 mt-4">部品寸法・単価、筐体、判定ルール、変換辞書、AI の接続を管理します。判定と見積はすべてここに定義した値に基づきます。</div>
          </div>
          <Badge cls={can('master', user) ? 'badge-blue' : 'badge-amber'}><BookOpen size={12} />{can('master', user) ? '編集できます（設計課長）' : '閲覧のみ・編集は設計課長'}</Badge>
        </div>
        <div style={{ width: 'fit-content', marginBottom: 14 }}>
          <SegTabs id="master" value={tab} onChange={(v) => navigate(`/master/${v}`)} items={TABS.map((t) => ({ id: t.id, label: <><t.icon size={14} />{t.label}</> }))} />
        </div>
        <motion.div className="card" key={tab} variants={fadeUp} initial="hidden" animate="show">
          {tab === 'parts' && <PartsTab />}
          {tab === 'enclosures' && <EnclosuresTab />}
          {tab === 'rules' && <RulesTab />}
          {tab === 'dictionary' && <DictionaryTab />}
          {tab === 'learning' && <LearningTab />}
          {tab === 'past' && <PastProjectsTab />}
          {tab === 'ai' && <AiTab />}
        </motion.div>
      </div>
    </div>
  )
}
