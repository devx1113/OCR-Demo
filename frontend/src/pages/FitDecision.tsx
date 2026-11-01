import { useState } from 'react'
import { motion } from 'framer-motion'
import { Check, ClipboardCheck, PenLine, TriangleAlert, Undo2 } from 'lucide-react'
import { api, can } from '../api'
import { useUser } from '../App'
import { Badge, dt, fadeUp } from '../ui'
import type { Ctx } from './ProjectPage'

const VJA: Record<string, string> = { ok: '可', ng: '不可', insufficient: '判定不能' }

/** 収容判定に対する設計者の最終判断（G4：判定一致率の記録。見積の計算は変えない） */
export default function FitDecision({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const user = useUser()
  const fit = project.analysis!.fit
  const r = project.fit_review
  const [form, setForm] = useState(false)
  const [verdict, setVerdict] = useState<'ok' | 'ng'>(fit.verdict === 'ok' ? 'ng' : 'ok')
  const [enc, setEnc] = useState('')
  const [reason, setReason] = useState('')
  const editable = can('edit', user)
  const sysNow = { verdict: fit.verdict, enclosure: fit.enclosure?.name ?? null }
  const drifted = r && (r.system.verdict !== sysNow.verdict || r.system.enclosure !== sysNow.enclosure)

  const submit = (b: Parameters<typeof api.fitReview>[1]) =>
    act(() => api.fitReview(project.id, b), '設計者の最終判断を記録しました').then((ok) => ok && setForm(false))

  return (
    <motion.div className="card fitdec" variants={fadeUp} data-testid="fit-decision">
      <div className="card-head"><ClipboardCheck size={17} color="var(--ai-500)" /><h3>設計者の最終判断</h3><span className="spacer" />
        {r && (r.decision === 'agree' ? <Badge cls="badge-green"><Check size={12} />判定どおり</Badge> : <Badge cls="badge-amber">異なる判断</Badge>)}</div>
      <div className="card-body col gap-10">
        {!r && !form && (
          <>
            <div className="small text-2">
              システムの判定（<b>{VJA[fit.verdict] ?? fit.verdict}</b>{fit.enclosure ? `・${fit.enclosure.name}` : ''}）に対する設計者の判断を記録します。
              記録は「精度・効果レポート → 判定一致率」に集計され、判定ルールの改善に使います。
            </div>
            {editable && (
              <div className="row gap-8">
                <button className="btn btn-sm btn-primary" onClick={() => submit({ decision: 'agree' })} data-testid="fit-agree"><Check size={14} />判定どおりで良い</button>
                <button className="btn btn-sm" onClick={() => setForm(true)}><PenLine size={14} />異なる判断を記録</button>
              </div>
            )}
          </>
        )}
        {form && (
          <div className="col gap-8">
            <div className="row gap-12 small">
              <span className="text-2">設計者の判断</span>
              {(['ok', 'ng'] as const).map((v) => (
                <label key={v} className="row gap-4"><input type="radio" name="fitdec" checked={verdict === v} onChange={() => setVerdict(v)} />{VJA[v]}</label>
              ))}
            </div>
            <input className="input input-sm" placeholder="採用する筐体（例：自立形 W800×H2000×D700）" value={enc} list="fitdec-enc" onChange={(e) => setEnc(e.target.value)} />
            <datalist id="fitdec-enc">{[fit.enclosure?.name, ...fit.alternatives.map((a) => a.name)].filter(Boolean).map((n) => <option key={n!} value={n!} />)}</datalist>
            <textarea className="input" rows={2} placeholder="理由（必須）：例）ダクト幅を 40mm に詰めれば W800 で収まる" value={reason} onChange={(e) => setReason(e.target.value)} />
            <div className="row gap-8">
              <span className="spacer" />
              <button className="btn btn-sm btn-ghost" onClick={() => setForm(false)}>キャンセル</button>
              <button className="btn btn-sm btn-primary" disabled={!reason.trim()}
                onClick={() => submit({ decision: 'disagree', final_verdict: verdict, final_enclosure: enc, reason })}>記録する</button>
            </div>
          </div>
        )}
        {r && (
          <>
            <div className="fitdec-row">
              <div><span className="xs muted">システム（記録時）</span><b>{VJA[r.system.verdict] ?? r.system.verdict}</b><span className="xs muted">{r.system.enclosure}</span></div>
              <div><span className="xs muted">設計者</span><b>{VJA[r.final_verdict] ?? r.final_verdict}</b><span className="xs muted">{r.final_enclosure}</span></div>
            </div>
            {r.reason && <div className="small text-2">理由：{r.reason}</div>}
            <div className="row xs muted">{r.by} ・ {dt(r.at)}<span className="spacer" />
              {editable && <button className="btn btn-xs btn-ghost" onClick={() => act(() => api.fitReviewReset(project.id), '最終判断の記録を取り消しました')}><Undo2 size={12} />取り消す</button>}</div>
            {drifted && (
              <div className="banner banner-amber small"><TriangleAlert size={14} />
                <span>記録後に判定結果が変わりました（現在：{VJA[sysNow.verdict] ?? sysNow.verdict}{sysNow.enclosure ? `・${sysNow.enclosure}` : ''}）。必要なら記録し直してください。</span></div>
            )}
          </>
        )}
      </div>
    </motion.div>
  )
}
