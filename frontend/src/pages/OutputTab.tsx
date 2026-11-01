import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  BadgeCheck, Check, CircleAlert, Clock, Copy, Download, FileCheck2, FileQuestion, FileSpreadsheet, Lock, Mail, Maximize2, MessageSquarePlus,
  RefreshCw, Send, Share2, ShieldCheck, Sparkles, Trash2, Undo2, XCircle,
} from 'lucide-react'
import { ApiError, USERS, api, can, fetchExport, saveBlob } from '../api'
import { useAi, useUser } from '../App'
import { Badge, DateStamp, Modal, Spinner, StampOverlay, dt, fadeUp, stagger, useToast, yen } from '../ui'
import { PlainPdf } from '../viewer'
import type { Ctx } from './ProjectPage'

const CELL_LABEL: Record<string, string> = {
  customer: '宛先（発注者）', quote_no: '見積番号', date: '見積日', owner: '担当', subject: '件名', delivery: '納期',
  delivery_place: '受渡場所', validity: '有効期限', draft_mark: 'ドラフト表示', approver: '承認者', creator: '作成者',
}
type CellMap = {
  cover: { sheet: string; cells: Record<string, string> }
  lines: { sheet: string; start_row: number; max_rows: number; cols: Record<string, string> }
  conditions: { sheet: string; start_row: number; max_rows: number; col: string }
  equipment: { sheet: string; start_row: number; max_rows: number }
}

const stampDate = (iso?: string) => {
  const d = iso ? new Date(iso) : new Date()
  return `${String(d.getFullYear()).slice(2)}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}
const family = (name: string) => name.split(/\s/)[0]

const roleOf = (name?: string | null) => USERS.find((u) => u.name === name)?.role ?? ''

/** 承認フロー：担当が依頼 → 課長が承認（または差戻し）。承認のたびに見積の版が記録される */
function ApprovalFlow({ ctx, blocking, onApproved }: { ctx: Ctx; blocking: number; onApproved: () => void }) {
  const { project, act } = ctx
  const user = useUser()
  const a = project.analysis!
  const ap = project.approval
  const st = ap?.status
  const [comment, setComment] = useState('')
  const revs = project.revisions || []
  const steps = [
    { key: 'make', label: '作成・確認', who: project.owner, done: blocking === 0, at: a.analyzed_at },
    { key: 'req', label: '承認依頼', who: st === 'requested' ? ap!.by : ap?.requested_by ?? undefined,
      done: st === 'requested' || (st === 'approved' && !!ap?.requested_by) || st === 'returned', at: st === 'requested' ? ap!.at : ap?.requested_at ?? undefined },
    { key: 'ok', label: '課長承認', who: st === 'approved' ? ap!.by : undefined, done: st === 'approved', at: st === 'approved' ? ap!.at : undefined },
  ]
  const run = async (fn: () => Promise<import('../types').Project>, msg: string, after?: () => void) => {
    if (await act(fn, msg)) { setComment(''); after?.() }
  }

  return (
    <div className="col gap-12">
      <div className="ap-flow" aria-label="承認の流れ">
        {steps.map((x, i) => (
          <div key={x.key} className={`ap-step ${x.done ? 'done' : ''} ${!x.done && (i === 0 || steps[i - 1].done) ? 'now' : ''} ${x.key === 'req' && st === 'returned' ? 'returned' : ''}`}>
            <span className="ap-dot">{x.done ? <Check size={13} strokeWidth={3} /> : i + 1}</span>
            <span className="ap-label">{x.key === 'req' && st === 'returned' ? '差戻し' : x.label}</span>
            <span className="ap-who">{x.who ? `${x.who}${x.at ? `・${dt(x.at).slice(5)}` : ''}` : '—'}</span>
            {i < steps.length - 1 && <span className="ap-line" aria-hidden />}
          </div>
        ))}
      </div>

      {st === 'approved' ? (
        <motion.div className="approved-card row gap-16" initial={{ opacity: 0 }} animate={{ opacity: 1 }} data-testid="approved">
          <DateStamp top="承認" date={stampDate(ap!.at)} name={family(ap!.by)} size={104} />
          <div className="grow">
            <div className="row gap-8"><span className="bold head" style={{ fontSize: 16 }}>承認済み：{ap!.by}</span>{ap!.rev && <span className="rev-badge">第{ap!.rev}版</span>}</div>
            <div className="small text-2">{dt(ap!.at)} ・ 承認時の見積金額 {yen(ap!.sale_total)}（税抜）</div>
            {ap!.requested_by && <div className="xs text-2">依頼：{ap!.requested_by}（{dt(ap!.requested_at)}）</div>}
            {ap!.comment && <div className="small mt-4">「{ap!.comment}」</div>}
            <div className="xs muted mt-4">承認後に内容を変更すると、承認は自動で取り消されます。</div>
          </div>
          {can('approve', user) && <button className="btn btn-sm" onClick={() => act(() => api.unapprove(project.id), '承認を取り消しました')}>承認を取消</button>}
        </motion.div>
      ) : (
        <>
          {st === 'revoked' && <div className="banner banner-amber small"><RefreshCw size={14} />内容の変更により承認が取り消されています（{ap!.by}・{dt(ap!.at)}）</div>}
          {st === 'withdrawn' && <div className="banner banner-amber small"><RefreshCw size={14} />依頼後に内容が変更されたため、承認依頼を取り下げました（{ap!.by}・{dt(ap!.at)}）。再度依頼してください。</div>}
          {st === 'returned' && (
            <motion.div className="ap-note returned" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
              <Undo2 size={15} /><div className="grow"><b>差戻し：{ap!.by}（{roleOf(ap!.by)}）</b>・{dt(ap!.at)}<div className="small mt-4">「{ap!.comment}」</div></div>
            </motion.div>
          )}
          {st === 'requested' && (
            <motion.div className="ap-note requested" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
              <Clock size={15} /><div className="grow"><b>{ap!.by} さんが承認を依頼しています</b>・{dt(ap!.at)}・見積金額 {yen(ap!.sale_total)}（税抜）
                {ap!.comment && <div className="small mt-4">「{ap!.comment}」</div>}</div>
            </motion.div>
          )}

          {(can('approve', user) || (can('request', user) && st !== 'requested')) ? (
            <div className="col gap-8">
              <textarea className="textarea" rows={2} value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder={can('approve', user) ? (st === 'requested' ? '承認コメント／差戻しの理由' : '承認コメント（任意）') : '依頼コメント（任意）'} aria-label="承認コメント" />
              <div className="row-wrap">
                <span className="small text-2 grow">{user}（{roleOf(user)}）・ 見積金額 {yen(a.estimate.sale_total)}（税抜）{revs.length ? ` ・ 次は第${revs.length + 1}版` : ''}</span>
                {can('approve', user) && st === 'requested' && (
                  <button className="btn btn-lg" disabled={!comment.trim()} title={comment.trim() ? '' : '差戻しの理由を入力してください'}
                    onClick={() => run(() => api.returnApproval(project.id, comment), '差し戻しました')}><Undo2 size={16} />差戻し</button>
                )}
                {can('approve', user) ? (
                  <button className="btn btn-lg btn-shu" disabled={blocking > 0} onClick={() => run(() => api.approve(project.id, comment), '', onApproved)}>
                    <BadgeCheck size={17} />承認する
                  </button>
                ) : (
                  <button className="btn btn-lg btn-primary" disabled={blocking > 0} onClick={() => run(() => api.requestApproval(project.id, comment), '設計課長に承認を依頼しました')}>
                    <Send size={16} />承認を依頼
                  </button>
                )}
              </div>
              {blocking > 0 && <div className="xs" style={{ color: 'var(--danger)' }}>未解決の事項が {blocking} 件あるため、{can('approve', user) ? '承認' : '承認依頼'}できません。</div>}
            </div>
          ) : (
            <div className="ap-note lock"><Lock size={15} /><div className="grow small">
              {st === 'requested' ? '設計課長の承認待ちです。担当者を「佐藤 花子（設計課長）」に切り替えると承認できます。' : `${roleOf(user)}には承認依頼・承認の権限がありません。`}
            </div></div>
          )}
        </>
      )}
    </div>
  )
}

function EmailModal({ ctx, onClose }: { ctx: Ctx; onClose: () => void }) {
  const toast = useToast()
  const [kind, setKind] = useState<'quote' | 'questions'>('quote')
  const [busy, setBusy] = useState(false)
  const [mail, setMail] = useState<{ subject: string; body: string; meta: string } | null>(null)
  const gen = async (k: 'quote' | 'questions') => {
    setKind(k)
    setBusy(true)
    try {
      const r = await api.aiEmail(ctx.project.id, k)
      setMail({ subject: r.subject, body: r.body, meta: `${r.usage.model} ・ ${r.usage.seconds}秒` })
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const copy = async () => {
    if (!mail) return
    try {
      await navigator.clipboard.writeText(`件名：${mail.subject}\n\n${mail.body}`)
      toast('件名と本文をコピーしました', 'success')
    } catch {
      toast('クリップボードにコピーできませんでした', 'error')
    }
  }
  return (
    <Modal title={<span className="row"><Sparkles size={18} color="#b14dff" /><span className="magic-text">AI メール文案</span></span>} width={760} onClose={onClose}
      footer={mail && <>
        <span className="xs muted grow">{mail.meta} ・ 送信前に必ず内容をご確認ください</span>
        <a className="btn" href={`mailto:?subject=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(mail.body)}`}><Mail size={15} />メールソフトで開く</a>
        <button className="btn btn-primary" onClick={copy}><Copy size={15} />コピー</button>
      </>}>
      <div className="row gap-8">
        <button className={`btn btn-sm ${kind === 'quote' && mail ? 'btn-soft' : ''}`} disabled={busy} onClick={() => gen('quote')}>見積提出メール</button>
        <button className={`btn btn-sm ${kind === 'questions' && mail ? 'btn-soft' : ''}`} disabled={busy} onClick={() => gen('questions')}>質疑確認メール</button>
        <span className="small muted">金額・見積番号・前提条件・質疑は解析結果から自動で差し込みます</span>
      </div>
      {busy && <div className="thinking"><div className="thinking-orb" /><div className="bold">ビジネス敬語でメール文案を作成しています…</div></div>}
      {!busy && !mail && <div className="empty small">作成するメールの種類を選んでください</div>}
      {!busy && mail && (
        <motion.div className="col gap-8 mt-12" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <label className="label">件名</label>
          <input className="input" value={mail.subject} onChange={(e) => setMail({ ...mail, subject: e.target.value })} aria-label="件名" />
          <label className="label mt-8">本文</label>
          <textarea className="textarea" rows={16} value={mail.body} onChange={(e) => setMail({ ...mail, body: e.target.value })} aria-label="本文" />
        </motion.div>
      )}
    </Modal>
  )
}

export default function OutputTab({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const toast = useToast()
  useUser() // 担当者の切替で権限に応じた表示に更新する
  const { ai } = useAi()
  const a = project.analysis!
  const blocking = a.issues.filter((i) => i.blocking)
  const warnings = a.issues.filter((i) => !i.blocking)
  const approved = project.approval?.status === 'approved'
  const [busy, setBusy] = useState<string | null>(null)
  const [blocked, setBlocked] = useState<{ title: string; detail: string }[] | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfState, setPdfState] = useState<'idle' | 'loading' | 'error' | 'unavailable' | 'noperm'>('idle')
  const [cellmap, setCellmap] = useState<CellMap | null>(null)
  const [q, setQ] = useState('')
  const [zoom, setZoom] = useState(false)
  const [stamping, setStamping] = useState(false)
  const [mailOpen, setMailOpen] = useState(false)

  const previewKey = `${a.analyzed_at}|${project.approval?.status}|${project.approval?.at}`
  useEffect(() => {
    let url: string | null = null
    let alive = true
    setPdfState('loading')
    api.health().then((h) => {
      if (!h.pdf_preview) { setPdfState('unavailable'); return }
      if (!approved && !can('draft')) { setPdfState('noperm'); return }
      return fetchExport(project.id, 'estimate-pdf', true).then(({ blob }) => {
        if (!alive) return
        url = URL.createObjectURL(blob)
        setPdfUrl(url)
        setPdfState('idle')
      })
    }).catch(() => alive && setPdfState('error'))
    return () => { alive = false; if (url) URL.revokeObjectURL(url) }
  }, [previewKey, project.id, approved])
  useEffect(() => { api.master<CellMap>('cellmap').then(setCellmap).catch(() => {}) }, [])

  const download = async (kind: string, force = false) => {
    setBusy(kind)
    try {
      const { blob, filename } = await fetchExport(project.id, kind, force)
      saveBlob(blob, filename)
      toast(`${filename} を出力しました`, 'success')
      setBlocked(null)
      ctx.act(() => api.project(project.id))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && (e.data as { blocking?: unknown })?.blocking) {
        setBlocked((e.data as { blocking: { title: string; detail: string }[] }).blocking)
      } else toast((e as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="page">
      <motion.div className="page-narrow two-col" style={{ '--side': '540px' } as React.CSSProperties} variants={stagger} initial="hidden" animate="show">
        <div className="col gap-20">
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><ShieldCheck size={18} color="var(--ai-500)" /><h3>出力前チェック</h3><span className="spacer" />
              {blocking.length ? <Badge cls="badge-solid-red">未解決 {blocking.length}</Badge> : <Badge cls="badge-solid-green">承認可能</Badge>}</div>
            <div className="card-body col gap-8">
              {blocking.length === 0 && <div className="banner banner-green"><BadgeCheck size={16} />承認前に解決が必要な事項はありません。</div>}
              {blocking.map((i) => (
                <div key={i.id} className="row small" style={{ alignItems: 'flex-start' }}>
                  <XCircle size={15} color="var(--danger)" style={{ marginTop: 2, flexShrink: 0 }} />
                  <div className="grow"><b>{i.title}</b><div className="text-2">{i.detail}</div></div>
                  <button className="btn btn-xs" onClick={() => ctx.go(i.target?.kind === 'fit' ? 'fit' : 'review', i.target)}>確認する</button>
                </div>
              ))}
              {warnings.length > 0 && <div className="xs muted mt-8 bold">注意事項（出力は可能）</div>}
              {warnings.map((i) => (
                <div key={i.id} className="row small" style={{ alignItems: 'flex-start' }}>
                  <CircleAlert size={15} color={i.severity === 'low' ? 'var(--info)' : 'var(--warn)'} style={{ marginTop: 2, flexShrink: 0 }} />
                  <div className="grow"><b>{i.title}</b><span className="text-2" style={{ marginLeft: 10 }}>{i.detail}</span></div>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><BadgeCheck size={18} color="var(--shu-500)" /><h3>承認</h3><span className="spacer" />
              {(project.revisions || []).length > 0 && <button className="btn btn-xs btn-ghost" onClick={() => ctx.go('history')}>見積の版（{project.revisions!.length}）</button>}</div>
            <div className="card-body">
              <ApprovalFlow ctx={ctx} blocking={blocking.length} onApproved={() => setStamping(true)} />
            </div>
          </motion.div>

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>出力ファイル</h3><span className="spacer" />
              <button className="btn btn-sm btn-magic" disabled={!ai.enabled} onClick={() => setMailOpen(true)} title={ai.enabled ? '' : 'AI が接続されていません'}>
                <Sparkles size={14} />送付メールを AI で作成
              </button></div>
            <motion.div className="card-body col gap-12" variants={stagger} initial="hidden" animate="show">
              {[
                { kind: 'estimate', icon: <FileSpreadsheet size={22} />, bg: 'var(--grad-ok)', title: '見積書（Excel）', desc: `既存雛形に転記・数式と書式を保持 ・ ${approved ? '承認済' : '未承認のためドラフト表示付き'}` },
                { kind: 'questions', icon: <FileQuestion size={22} />, bg: 'var(--grad-magic)', title: `質疑書（Excel・${a.questions.length}件）`, desc: '記載なし・資料間の相違・仕様変更の提案を顧客確認用に整理' },
                { kind: 'basis', icon: <FileCheck2 size={22} />, bg: 'var(--grad-ai)', title: '見積根拠書（Excel・社内用）', desc: '抽出値と出典・マスタ照合・判定根拠・原価内訳・操作履歴' },
              ].map((f) => (
                <motion.div key={f.kind} className="out-file" variants={fadeUp}>
                  <div className="kpi-icon" style={{ background: f.bg }}>{f.icon}</div>
                  <div className="grow"><div className="bold head">{f.title}</div><div className="small text-2">{f.desc}</div></div>
                  <button className="btn btn-sm btn-primary" disabled={busy !== null} onClick={() => download(f.kind)} aria-label={`${f.title}を出力`}>
                    {busy === f.kind ? <Spinner size={13} /> : <Download size={14} />}出力
                  </button>
                </motion.div>
              ))}
              {project.exported_at && <div className="xs muted">承認後の最終出力：{dt(project.exported_at)}</div>}
            </motion.div>
          </motion.div>

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><Share2 size={18} color="var(--ai-500)" /><h3>他システム連携（CSV）</h3><span className="spacer" />
              <span className="small muted">販売管理・ERP・購買システムへの取込用</span></div>
            <div className="card-body col gap-10">
              {[
                { kind: 'sales-csv', title: '見積明細（販売管理・ERP）', desc: `顧客提出の明細 ${a.estimate.customer_lines.length} 行・小計・消費税・合計` },
                { kind: 'purchase-csv', title: '手配リスト（購買）', desc: `筐体・機器・予備品の型式・メーカー・数量・原価単価（要見積・期限切れの印付き・社内用）` },
              ].map((f) => (
                <div key={f.kind} className="out-file out-csv">
                  <div className="file-icon csv" style={{ width: 34, height: 40, fontSize: 8, paddingBottom: 5 }}>CSV</div>
                  <div className="grow"><div className="bold">{f.title}</div><div className="xs text-2">{f.desc}</div></div>
                  <button className="btn btn-sm" disabled={busy !== null || blocking.length > 0} onClick={() => download(f.kind)} aria-label={`${f.title}を出力`}
                    title={blocking.length ? '未解決の要確認事項があるため出力できません' : ''}>
                    {busy === f.kind ? <Spinner size={13} /> : <Download size={14} />}CSV
                  </button>
                </div>
              ))}
              <div className="xs muted">文字コードは BOM 付き UTF-8（Excel でそのまま開けます）。列の並びは連携先に合わせて本開発で調整します。{approved ? '' : '承認前の出力は「未承認」と記録されます。'}</div>
            </div>
          </motion.div>

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><FileQuestion size={18} color="#7b4dff" /><h3>質疑書の内容</h3><span className="spacer" /><Badge cls="badge-purple">{a.questions.length} 件</Badge></div>
            {a.questions.length === 0 && <div className="empty small">質疑事項はありません</div>}
            {a.questions.map((x) => (
              <div key={x.no} className="frow" style={{ cursor: 'default' }}>
                <div className="frow-top">
                  <span className="bold num head">No.{x.no}</span><Badge cls="badge-gray">{x.category}</Badge><span className="small bold">{x.item}</span>
                  <span className="spacer" />
                  {x.custom_id && <button className="btn btn-ghost btn-xs" aria-label="質疑を削除" onClick={() => act(() => api.deleteQuestion(project.id, x.custom_id!), '質疑を削除しました')}><Trash2 size={12} /></button>}
                </div>
                <div className="small mt-4">{x.question}</div>
                {x.refs.length > 0 && <div className="xs muted mt-4">参照：{x.refs.join(' ／ ')}</div>}
              </div>
            ))}
            <div className="card-foot row">
              <input className="input input-sm grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="質疑を手動で追加（例：立会検査の日程・人数についてご教示ください）" aria-label="追加する質疑" />
              <button className="btn btn-sm" disabled={!q.trim()} onClick={async () => { if (await act(() => api.addQuestion(project.id, { question: q }), '質疑を追加しました')) setQ('') }}>
                <MessageSquarePlus size={14} />追加
              </button>
            </div>
          </motion.div>
        </div>

        <div className="col gap-20" style={{ position: 'sticky', top: 0 }}>
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>見積書プレビュー</h3><span className="xs muted">Excel 出力を PDF 化</span><span className="spacer" />
              <button className="btn btn-xs" disabled={!pdfUrl || pdfState !== 'idle'} onClick={() => setZoom(true)}><Maximize2 size={12} />拡大</button></div>
            <div style={{ background: 'linear-gradient(180deg,#e9ecf7,#e2e6f4)', height: 650, overflow: 'auto', padding: 14, borderRadius: '0 0 16px 16px' }} data-testid="pdf-preview">
              {pdfState === 'loading' && <div className="empty"><Spinner size={24} /><div className="small mt-8">プレビューを生成しています…</div></div>}
              {pdfState === 'unavailable' && <div className="empty small">LibreOffice が見つからないため、プレビューは表示できません（Excel 出力は利用できます）。</div>}
              {pdfState === 'error' && <div className="empty small">プレビューを生成できませんでした。</div>}
              {pdfState === 'noperm' && <div className="empty small">承認前の見積書（ドラフト）は表示できません。承認後にプレビューと出力ができます。</div>}
              {pdfState === 'idle' && pdfUrl && <PlainPdf url={pdfUrl} scale={0.8} />}
            </div>
          </motion.div>
          {cellmap && (
            <motion.div className="card" variants={fadeUp}>
              <div className="card-head"><h3>雛形のセル対応表</h3><span className="spacer" /><span className="xs muted">cellmap.json で雛形ごとに定義</span></div>
              <table className="table" style={{ fontSize: 12 }}>
                <tbody>
                  {Object.entries(cellmap.cover.cells).map(([k, ref]) => (
                    <tr key={k}><td>{CELL_LABEL[k] || k}</td><td className="mono right">{cellmap.cover.sheet}!{ref}</td></tr>
                  ))}
                  <tr><td>明細行（最大 {cellmap.lines.max_rows} 行）</td><td className="mono right">{cellmap.lines.sheet}!{cellmap.lines.cols.no}{cellmap.lines.start_row}〜</td></tr>
                  <tr><td>見積条件（最大 {cellmap.conditions.max_rows} 行）</td><td className="mono right">{cellmap.conditions.sheet}!{cellmap.conditions.col}{cellmap.conditions.start_row}〜</td></tr>
                  <tr><td>主要機器構成（最大 {cellmap.equipment.max_rows} 行）</td><td className="mono right">{cellmap.equipment.sheet}!A{cellmap.equipment.start_row}〜</td></tr>
                </tbody>
              </table>
              <div className="card-foot xs muted">金額・小計・消費税は雛形の数式で計算されます（システム側でも同じ計算で検算）。</div>
            </motion.div>
          )}
        </div>
      </motion.div>

      {zoom && pdfUrl && (
        <Modal title="見積書プレビュー" width={980} onClose={() => setZoom(false)}>
          <div style={{ background: '#e9ecf7', height: '72vh', overflow: 'auto', padding: 16, borderRadius: 10 }}><PlainPdf url={pdfUrl} scale={1.35} /></div>
        </Modal>
      )}
      {mailOpen && <EmailModal ctx={ctx} onClose={() => setMailOpen(false)} />}
      {blocked && (
        <Modal title="未解決の要確認事項があります" onClose={() => setBlocked(null)}
          footer={<><button className="btn" onClick={() => setBlocked(null)}>戻って確認する</button>
            <button className="btn btn-danger" onClick={() => download('estimate', true)}><Download size={14} />注意書き付きで出力</button></>}>
          <div className="small text-2">以下の事項が未解決です。正式な見積書は解決・承認後に出力してください。社内確認用に、ドラフト表示と前提条件の注意書きを付けて出力することもできます。</div>
          <div className="col gap-8 mt-12">
            {blocked.map((b) => (
              <div key={b.title} className="row small" style={{ alignItems: 'flex-start' }}><XCircle size={15} color="var(--danger)" style={{ marginTop: 2 }} /><div><b>{b.title}</b><div className="text-2">{b.detail}</div></div></div>
            ))}
          </div>
        </Modal>
      )}
      <AnimatePresence>
        {stamping && project.approval && (
          <StampOverlay onDone={() => setStamping(false)}>
            <DateStamp top="承認" date={stampDate(project.approval.at)} name={family(project.approval.by)} size={280} />
          </StampOverlay>
        )}
      </AnimatePresence>
    </div>
  )
}
