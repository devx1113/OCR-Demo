import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowRight, Archive, BadgeCheck, Check, History, Lightbulb, Lock, RotateCcw, Save, TriangleAlert, X } from 'lucide-react'
import { api, can } from '../api'
import { navigate, useUser } from '../App'
import type { ImpactChange, ImpactResult, ImpactRow, LearningResult, MasterSaveResult, MasterVersion } from '../types'
import { Badge, Empty, Modal, Spinner, dt, fadeUp, stagger, useToast, yen } from '../ui'

const APPROVAL_JA: Record<string, { label: string; cls: string }> = {
  approved: { label: '承認済', cls: 'badge-green' }, requested: { label: '承認待ち', cls: 'badge-purple' },
}

function fmt(c: ImpactChange, v: ImpactChange['a']) {
  if (v == null) return '—'
  return c.kind === 'sale_total' && typeof v === 'number' ? yen(v) : String(v)
}

function ChangeChip({ c }: { c: ImpactChange }) {
  return (
    <span className={`imp-chip sev-${c.severity}`}>
      <b>{c.label}</b>{fmt(c, c.a)}<ArrowRight size={11} />{fmt(c, c.b)}
      {c.delta != null && <em className={c.delta > 0 ? 'up' : 'down'}>{c.delta > 0 ? '+' : ''}{yen(c.delta)}</em>}
    </span>
  )
}

/** 案件ごとの結果の変化（影響確認・回帰チェックで共通） */
export function ImpactTable({ rows, labels = ['現在', '変更後'] }: { rows: ImpactRow[]; labels?: [string, string] | string[] }) {
  return (
    <table className="table imp-table">
      <thead><tr><th>見積番号</th><th>案件名</th><th>{labels[0]} → {labels[1]}</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="clickable" onClick={() => navigate(`/projects/${r.id}/fit`)}>
            <td className="mono nowrap">{r.quote_no}</td>
            <td>
              <div className="bold">{r.name}</div>
              {r.locked && r.approval && <Badge cls={APPROVAL_JA[r.approval]?.cls ?? 'badge-gray'}><Lock size={11} />{APPROVAL_JA[r.approval]?.label}・自動では再計算しません</Badge>}
            </td>
            <td>
              {r.changed ? <div className="imp-chips">{r.changes.map((c) => <ChangeChip key={c.kind} c={c} />)}</div>
                : <span className="small muted">変化なし</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 保存前に、変更したマスタで全案件を再解析して結果の変化を示し、確認してから保存する（C13） */
export function ImpactDialog({ name, title, data, onClose, onSaved }: {
  name: string; title: string; data: unknown; onClose: () => void; onSaved: (r: MasterSaveResult) => void
}) {
  const toast = useToast()
  const [r, setR] = useState<ImpactResult | null>(null)
  const [err, setErr] = useState('')
  const [recompute, setRecompute] = useState(true)
  const [saving, setSaving] = useState(false)
  useEffect(() => { api.masterImpact(name, data).then(setR).catch((e) => setErr(e.message)) }, [name, data])
  const save = async () => {
    setSaving(true)
    try {
      const res = await api.saveMaster(name, data, recompute)
      toast(`${title}を第${res.version}版として保存しました${res.recomputed.length ? `（${res.recomputed.length} 件を再計算）` : ''}`, 'success')
      onSaved(res)
    } catch (e) {
      toast((e as Error).message, 'error')
      setSaving(false)
    }
  }
  const unlocked = r ? r.rows.filter((x) => x.changed && !x.locked).length : 0
  return (
    <Modal title={<span className="row gap-8"><History size={17} color="var(--ai-500)" />変更の影響を確認</span>} onClose={onClose} width={780} label="変更の影響を確認"
      footer={<>
        <span className="small muted grow">{r?.summary}</span>
        <button className="btn" onClick={onClose}>キャンセル</button>
        <button className="btn btn-primary" onClick={save} disabled={!r || saving} data-testid="impact-save">{saving ? <Spinner size={14} /> : <Save size={14} />}保存する</button>
      </>}>
      {err && <div className="banner banner-red">{err}</div>}
      {!r && !err && <div className="empty"><Spinner size={22} /><div className="small muted mt-8">保存前の内容で全案件を再解析しています…</div></div>}
      {r && (
        <motion.div className="col gap-14" variants={stagger} initial="hidden" animate="show">
          <motion.div className="imp-kpis" variants={fadeUp}>
            <div><span>再解析した案件</span><b className="num">{r.total}</b></div>
            <div className={r.changed ? 'warn' : 'ok'}><span>結果が変わる案件</span><b className="num">{r.changed}</b></div>
            <div className={r.verdict_changed ? 'bad' : ''}><span>判定・筐体が変わる</span><b className="num">{r.verdict_changed}</b></div>
            <div><span>見積金額の増減（合計）</span><b className="num">{r.sale_delta > 0 ? '+' : ''}{yen(r.sale_delta)}</b></div>
          </motion.div>
          {r.locked_changed > 0 && (
            <motion.div className="banner banner-amber" variants={fadeUp}>
              <TriangleAlert size={16} />
              <span>承認済み・承認待ちの見積 <b>{r.locked_changed} 件</b>に影響があります。提出済みの金額を守るため自動では再計算しません。必要な場合は案件を開いて再解析し、再承認してください。</span>
            </motion.div>
          )}
          {r.changed === 0 && <motion.div className="banner banner-green" variants={fadeUp}><BadgeCheck size={16} />この変更で判定・金額が変わる案件はありません。</motion.div>}
          {r.changed > 0 && <motion.div variants={fadeUp} className="imp-scroll"><ImpactTable rows={r.rows.filter((x) => x.changed)} /></motion.div>}
          <motion.label className="row small" variants={fadeUp}>
            <input type="checkbox" checked={recompute} onChange={(e) => setRecompute(e.target.checked)} />
            結果が変わる作業中の案件（{unlocked} 件）を保存と同時に再計算する
          </motion.label>
        </motion.div>
      )}
    </Modal>
  )
}

/** マスタの版の一覧と、以前の版への戻し */
export function VersionsButton({ name, title, onRestored }: { name: string; title: string; onRestored: () => void }) {
  const toast = useToast()
  const user = useUser()
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<MasterVersion[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  useEffect(() => { if (open) api.masterVersions(name).then(setList) }, [open, name])
  const restore = async (v: number) => {
    setBusy(v)
    try {
      const r = await api.restoreMaster(name, v, true)
      toast(`第${v}版の内容に戻しました（第${r.version}版）${r.recomputed.length ? `・${r.recomputed.length} 件を再計算` : ''}`, 'success')
      setOpen(false)
      onRestored()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }
  return (
    <>
      <button className="btn btn-sm btn-ghost" onClick={() => setOpen(true)} data-testid={`versions-${name}`}><History size={14} />変更履歴</button>
      {open && (
        <Modal title={`${title}の変更履歴`} onClose={() => setOpen(false)} width={640} label={`${title}の変更履歴`}>
          {!list && <div className="empty"><Spinner /></div>}
          {list && list.length === 0 && <div className="empty small muted">まだ変更されていません（保存すると版として記録されます）</div>}
          {list && list.length > 0 && (
            <div className="ver-list">
              {list.map((v, i) => (
                <div key={v.version} className={`ver ${i === 0 ? 'current' : ''}`}>
                  <span className="ver-no num">第{v.version}版</span>
                  <div className="grow">
                    <div className="small bold">{v.summary}</div>
                    <div className="xs muted">{dt(v.at)} ・ {v.by}</div>
                  </div>
                  {i === 0 ? <Badge cls="badge-blue">現在</Badge>
                    : can('master', user) && <button className="btn btn-xs" disabled={busy !== null} onClick={() => restore(v.version)}>
                      {busy === v.version ? <Spinner size={12} /> : <RotateCcw size={12} />}この版に戻す</button>}
                </div>
              ))}
            </div>
          )}
          <div className="xs muted mt-12">戻すと新しい版として記録され、結果が変わる作業中の案件は再計算されます（承認済みの見積は変えません）。</div>
        </Modal>
      )}
    </>
  )
}

const KIND_TONE: Record<string, string> = {
  part_alias: 'badge-blue', name_alias: 'badge-blue', field_alias: 'badge-purple', unregistered: 'badge-amber', frequent_edit: 'badge-gray',
}

/** 担当者の修正から作った辞書・マスタの改善候補（F7）。反映は権限者が判断する */
export function LearningTab() {
  const toast = useToast()
  const user = useUser()
  const [r, setR] = useState<LearningResult | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => api.learning().then(setR)
  useEffect(() => { load() }, [])
  const decide = async (id: string, action: 'apply' | 'dismiss') => {
    setBusy(id)
    try {
      const res = await api.learningDecide(id, action)
      toast(action === 'apply' ? `${res.master === 'parts' ? '部品マスタ' : '変換辞書'}に反映しました（第${res.version}版）` : '候補を見送りました', 'success')
      await load()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }
  if (!r) return <div className="card-body"><Spinner /></div>
  const editable = can('master', user)
  return (
    <>
      <div className="card-head">
        <Lightbulb size={16} color="var(--kin-500, #b8860b)" />
        <span className="small text-2">担当者が案件で行った修正を集計した、変換辞書・部品マスタの改善候補です。自動では反映せず、内容を確認して「反映」したものだけを加えます。</span>
        <span className="spacer" />
        <Badge cls={r.open ? 'badge-amber' : 'badge-green'}>未判断 {r.open} 件</Badge>
      </div>
      <div className="card-body col gap-12">
        {r.items.length === 0 && (
          <Empty icon={<Lightbulb size={24} />} title="改善候補はありません">
            案件で型式の訂正、AI だけが読んだ値の確定、マスタにない機器の追加などを行うと、ここに辞書・マスタへの追加候補が表示されます。
          </Empty>
        )}
        <motion.div className="col gap-10" variants={stagger} initial="hidden" animate="show">
          {r.items.map((c) => (
            <motion.div key={c.id} className="learn" variants={fadeUp} data-testid="learn-item">
              <div className="row gap-8">
                <Badge cls={KIND_TONE[c.kind]}>{c.kind_ja}</Badge>
                <b className="grow">{c.title}</b>
                <span className="xs muted nowrap">{c.count} 案件</span>
              </div>
              <div className="small text-2 mt-4">{c.effect}</div>
              <div className="learn-ex">
                {c.examples.map((e) => <span key={e}>{e}</span>)}
              </div>
              <div className="row gap-8 mt-8">
                <span className="xs muted grow">{c.projects.map((p) => p.quote_no).join('・')}</span>
                {editable && (
                  <>
                    <button className="btn btn-xs btn-ghost" disabled={busy !== null} onClick={() => decide(c.id, 'dismiss')}><X size={12} />見送る</button>
                    {c.applicable && <button className="btn btn-xs btn-primary" disabled={busy !== null} onClick={() => decide(c.id, 'apply')}>
                      {busy === c.id ? <Spinner size={12} /> : <Check size={12} />}反映する</button>}
                  </>
                )}
              </div>
            </motion.div>
          ))}
        </motion.div>
        {r.decisions.length > 0 && (
          <div className="mt-12">
            <div className="section-title">判断の記録</div>
            {r.decisions.map((d) => (
              <div key={d.id + d.at} className="row small learn-done">
                {d.action === 'applied' ? <Check size={13} color="var(--ok)" /> : <X size={13} color="var(--muted)" />}
                <span className="grow">{d.title}</span>
                <span className="xs muted nowrap">{d.action === 'applied' ? '反映' : '見送り'} ・ {d.by} ・ {dt(d.at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

type PastCase = {
  quote_no: string; name: string; customer: string; date: string; result: string; designer: string; panel_type: string
  main_power: string; enclosure: string; sale_total: number; components: { model: string; qty: number }[]; note: string
}

/** 過去案件データ（類似案件検索の対象・閲覧のみ） */
export function PastProjectsTab() {
  const [list, setList] = useState<PastCase[] | null>(null)
  useEffect(() => { api.master<PastCase[]>('past_projects').then(setList) }, [])
  if (!list) return <div className="card-body"><Spinner /></div>
  return (
    <>
      <div className="card-head">
        <Archive size={16} color="var(--ai-500)" />
        <span className="small text-2">類似案件検索の対象となる過去の見積実績です（デモ版は架空データ・閲覧のみ）。本システムで承認した見積も自動で対象に加わります。</span>
        <span className="spacer" /><span className="small muted">{list.length} 件</span>
      </div>
      <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 250px)' }}>
        <table className="table" style={{ fontSize: 12.5 }}>
          <thead><tr><th>見積番号</th><th>案件名</th><th>結果</th><th>盤形式・電源</th><th>最終盤サイズ</th><th className="right">機器</th><th className="right">金額（税抜）</th></tr></thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.quote_no} title={c.note}>
                <td className="mono nowrap">{c.quote_no}<div className="xs muted">{c.date}</div></td>
                <td><b>{c.name}</b><div className="xs muted">{c.customer} ・ {c.designer}</div></td>
                <td><Badge cls={c.result === '受注' ? 'badge-green' : 'badge-gray'}>{c.result}</Badge></td>
                <td className="small">{c.panel_type}<div className="xs muted">{c.main_power}</div></td>
                <td className="small nowrap">{c.enclosure}</td>
                <td className="right num">{c.components.reduce((s, x) => s + x.qty, 0)} 点</td>
                <td className="right num bold">{yen(c.sale_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
