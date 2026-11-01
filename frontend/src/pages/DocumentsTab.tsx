import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Download, Eye, MailPlus, Play, RefreshCw, Ruler, ScanLine, Sparkles, Trash2, UploadCloud, XCircle } from 'lucide-react'
import { api, can } from '../api'
import { useAi } from '../App'
import type { DrawingCheck, Doc, OcrResult } from '../types'
import { Badge, Modal, Spinner, dt, fadeUp, stagger, useToast } from '../ui'
import type { Ctx } from './ProjectPage'

const ROLES: { id: Doc['role']; label: string }[] = [
  { id: 'main', label: '主仕様書' },
  { id: 'supplement', label: '補足資料' },
  { id: 'drawing', label: '図面' },
  { id: 'other', label: 'その他' },
]
const SAMPLES = ['送水ポンプ制御盤_製作仕様書.pdf', '仕様補足・変更連絡書_No1.docx', '外形図_スキャン.pdf', '顧客回答メール_仕様確認.pdf']

function FileIcon({ ext }: { ext: string }) {
  const k = ext.replace('.', '')
  return <div className={`file-icon ${['pdf', 'docx', 'xlsx'].includes(k) ? k : 'other'}`}>{k.toUpperCase().slice(0, 4) || 'FILE'}</div>
}

/** スキャン図面（画像PDF）の AI-OCR 結果：寸法注記と仕様の照合、書き起こし */
function OcrPanel({ projectId, doc, check, version, busy, canRun, onRun }: {
  projectId: string; doc: Doc; check?: DrawingCheck; version: string; busy: boolean; canRun: boolean; onRun: () => void
}) {
  const [res, setRes] = useState<OcrResult | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let alive = true
    api.ocrResult(projectId, doc.id).then((r) => alive && setRes(r)).catch(() => alive && setRes(null))
    return () => { alive = false }
  }, [projectId, doc.id, version])
  if (!res) {
    return (
      <div className="ocr-cta mt-8">
        <span className="ocr-cta-ic"><ScanLine size={16} /></span>
        <span className="grow small">画像のみの PDF です。<b>AI-OCR</b> で文字と寸法注記を読み取り、仕様と照合できます。</span>
        {canRun && <button className="btn btn-sm btn-magic" disabled={busy} onClick={onRun}>{busy ? <Spinner size={13} /> : <Sparkles size={13} />}AI-OCR で読み取る</button>}
      </div>
    )
  }
  const byAxis = Object.fromEntries((check?.items || []).map((i) => [i.axis.toUpperCase(), i]))
  return (
    <motion.div className="ocr-panel mt-8" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <div className="ocr-head">
        <span className="ocr-tag"><ScanLine size={12} />AI-OCR 読取済み</span>
        <span className="xs muted">{res.doc_kind}{res.drawing_no ? `・図番 ${res.drawing_no}` : ''}{res.scale ? `・尺度 ${res.scale}` : ''}</span>
        <span className="spacer" />
        <span className="xs muted">{res.model}・{res.usage.seconds}秒</span>
      </div>
      <div className="ocr-dims">
        {res.dimensions.map((d, i) => {
          const c = byAxis[d.axis]
          const bad = c && !c.match
          return (
            <motion.div key={i} className={`ocr-dim ${bad ? 'bad' : c ? 'ok' : ''}`} initial={{ scale: 0.7, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.1 + i * 0.08, type: 'spring', stiffness: 400, damping: 20 }}>
              <span className="ocr-dim-ax"><Ruler size={11} />{c?.label ?? d.axis}</span>
              <b>{d.text}</b>
              {c && (bad
                ? <span className="ocr-dim-st">仕様 {c.spec}mm{c.matches_before ? '（図面は変更前の値）' : ''}</span>
                : <span className="ocr-dim-st"><Check size={11} />仕様と一致</span>)}
            </motion.div>
          )
        })}
        {res.dimensions.length === 0 && <span className="xs muted">寸法の注記は見つかりませんでした</span>}
      </div>
      {check && check.mismatch.length > 0 && (
        <div className="banner banner-red mt-8" style={{ padding: '7px 11px', fontSize: 12 }}>
          <AlertTriangle size={14} />図面と仕様で寸法が異なります。質疑書に「最新図面のご提示」を追加しました。
        </div>
      )}
      {!check && <div className="xs muted mt-4">解析を実行すると、読み取った寸法を仕様と照合します。</div>}
      <button className="ocr-lines-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <ChevronDown size={13} style={{ transform: open ? 'rotate(180deg)' : undefined, transition: 'transform .2s' }} />書き起こし（{res.lines.length}行）
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div className="ocr-lines" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
            {res.lines.map((l) => <div key={l.id}><span className="mono xs muted">p.{l.page}</span>{l.text}</div>)}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function size(n: number) {
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

export default function DocumentsTab({ ctx }: { ctx: Ctx }) {
  const { project, act } = ctx
  const toast = useToast()
  const { ai } = useAi()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [uploading, setUploading] = useState<string[]>([])
  const [rereading, setRereading] = useState<string | null>(null)
  const [del, setDel] = useState<Doc | null>(null)

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files)
    setUploading(list.map((f) => f.name))
    for (const f of list) {
      if (await act(() => api.upload(project.id, f))) toast(`${f.name} を登録しました`, 'success')
    }
    setUploading([])
  }
  const reread = async (d: Doc) => {
    setRereading(d.id)
    try {
      const r = await api.aiRead(project.id, d.id, true)
      toast(r.kind === 'ocr'
        ? `AI-OCR：文字 ${r.stats.lines}行・寸法 ${r.stats.dimensions}件（${r.usage.seconds}秒）。再解析で仕様と照合します`
        : `AI 再読解：項目 ${r.stats.fields}・機器 ${r.stats.components}（${r.usage.seconds}秒）。再解析で反映されます`, 'success')
      await act(() => api.project(project.id))
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setRereading(null)
    }
  }

  const docs = project.documents
  const usable = docs.filter((d) => d.status !== 'error' && d.text_layer && d.include)
  const hasMain = usable.some((d) => d.role === 'main')
  const hasReply = docs.some((d) => d.filename === SAMPLES[3])
  const aiDocs = Object.fromEntries((project.analysis?.ai.docs || []).map((x) => [x.doc_id, x]))
  const drawings = Object.fromEntries((project.analysis?.drawings || []).map((g) => [g.doc_id, g]))
  const isScan = (d: Doc) => d.ext === '.pdf' && !d.text_layer && d.status !== 'error'

  return (
    <div className="page">
      <div className="page-narrow two-col" style={{ '--side': '340px', alignItems: 'stretch' } as React.CSSProperties}>
        <motion.div className="col gap-16" variants={stagger} initial="hidden" animate="show">
          <motion.div variants={fadeUp}
            className={`dropzone ${drag ? 'drag' : ''}`}
            onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) upload(e.dataTransfer.files) }}
          >
            <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.xlsx" onChange={(e) => e.target.files && upload(e.target.files)} />
            <motion.div className="empty-icon" style={{ marginBottom: 12 }} animate={{ y: [0, -6, 0] }} transition={{ duration: 2.4, repeat: Infinity }}>
              {uploading.length ? <Spinner size={24} /> : <UploadCloud size={28} />}
            </motion.div>
            <div className="head" style={{ fontSize: 17, fontWeight: 800 }}>{uploading.length ? `${uploading.join('、')} を取り込み中…` : '仕様書・補足資料・メールをドラッグ＆ドロップ'}</div>
            <div className="small muted mt-4">または クリックしてファイルを選択 ・ PDF / Word(.docx) / Excel(.xlsx) ・ 複数可</div>
          </motion.div>

          <motion.div className="card" variants={fadeUp}>
            <div className="card-head">
              <h3>登録資料</h3><Badge cls="badge-gray">{docs.length} 件</Badge>
              <span className="spacer" />
              <span className="small muted">種別・受領日・版は表紙から自動推定</span>
            </div>
            {docs.length === 0 && <div className="empty small">まだ資料が登録されていません</div>}
            <AnimatePresence initial={false}>
              {docs.map((d) => {
                const air = aiDocs[d.id]
                return (
                  <motion.div key={d.id} className="doc-card" style={{ opacity: d.include ? 1 : 0.55 }} layout
                    initial={{ opacity: 0, x: -20 }} animate={{ opacity: d.include ? 1 : 0.55, x: 0 }} exit={{ opacity: 0, height: 0 }}>
                    <FileIcon ext={d.ext} />
                    <div style={{ minWidth: 0 }}>
                      <div className="row-wrap">
                        <span className="bold ellipsis head" style={{ fontSize: 14.5 }}>{d.filename}</span>
                        {d.status === 'ok' && <Badge cls="badge-green"><CheckCircle2 size={12} />読取OK</Badge>}
                        {d.status === 'warning' && <Badge cls="badge-amber"><AlertTriangle size={12} />要注意</Badge>}
                        {d.status === 'error' && <Badge cls="badge-red"><XCircle size={12} />取込エラー</Badge>}
                        {air && <span className="ai-read"><Sparkles size={11} />AI 読解済み・項目 {air.stats.fields}／機器 {air.stats.components}{air.stats.corrections ? `／訂正 ${air.stats.corrections}` : ''}</span>}
                      </div>
                      {d.title && d.title !== d.filename && <div className="small text-2 ellipsis">{d.title}{d.doc_no ? `（${d.doc_no}）` : ''}</div>}
                      <div className="doc-meta">
                        <span>{size(d.size)}</span>
                        {d.pages != null && <span>{d.pages} ページ</span>}
                        {d.tables != null && <span>表 {d.tables} ・ ブロック {d.blocks}</span>}
                        <span>登録 {dt(d.uploaded_at)}（{d.uploaded_by}）</span>
                      </div>
                      {(isScan(d) ? [] : d.messages).map((m) => (
                        <div key={m} className={`banner ${d.status === 'error' ? 'banner-red' : 'banner-amber'} mt-8`} style={{ padding: '7px 11px', fontSize: 12 }}>
                          {d.status === 'error' ? <XCircle size={14} /> : <AlertTriangle size={14} />}{m}
                        </div>
                      ))}
                      {isScan(d) && (
                        <OcrPanel projectId={project.id} doc={d} check={drawings[d.id]} version={`${project.updated_at}`}
                          busy={rereading === d.id} canRun={ai.enabled && can('edit')} onRun={() => reread(d)} />
                      )}
                      {d.status !== 'error' && (
                        <div className="row-wrap mt-8">
                          <select className="select input-sm" aria-label="資料の種別" value={d.role} onChange={(e) => act(() => api.updateDoc(project.id, d.id, { role: e.target.value }))}>
                            {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                          </select>
                          <label className="row small muted gap-4">受領日
                            <input className="input input-sm" type="date" value={d.received_date || ''} onChange={(e) => act(() => api.updateDoc(project.id, d.id, { received_date: e.target.value }))} />
                          </label>
                          <label className="row small muted gap-4">版
                            <input className="input input-sm" style={{ width: 80 }} defaultValue={d.version || ''} onBlur={(e) => e.target.value !== (d.version || '') && act(() => api.updateDoc(project.id, d.id, { version: e.target.value }))} />
                          </label>
                          <label className="row small gap-4" title="解析対象に含める">
                            <input type="checkbox" checked={d.include} onChange={(e) => act(() => api.updateDoc(project.id, d.id, { include: e.target.checked }))} />解析対象
                          </label>
                        </div>
                      )}
                    </div>
                    <div className="row gap-4">
                      {ai.enabled && can('edit') && d.status !== 'error' && (d.text_layer || isScan(d)) && (
                        <button className="btn btn-ghost btn-icon btn-sm" title="AI で読み直す" aria-label={`${d.filename} を AI で読み直す`} disabled={rereading !== null} onClick={() => reread(d)}>
                          {rereading === d.id ? <Spinner size={14} /> : <RefreshCw size={15} />}
                        </button>
                      )}
                      {d.status !== 'error' && (
                        <a className="btn btn-ghost btn-icon btn-sm" title="原文を開く" href={api.docFileUrl(project.id, d.id)} target="_blank" rel="noreferrer"><Eye size={15} /></a>
                      )}
                      <button className="btn btn-ghost btn-icon btn-sm" title="削除" aria-label={`${d.filename} を削除`} onClick={() => setDel(d)}><Trash2 size={15} /></button>
                    </div>
                  </motion.div>
                )
              })}
            </AnimatePresence>
            {docs.length > 0 && (
              <div className="card-foot row">
                <span className="small text-2 grow">
                  {hasMain ? `解析対象 ${usable.length} 件。主仕様書を基準に、補足資料の変更・追加を受領日順に反映します。` : '主仕様書を1件以上指定してください。'}
                </span>
                <button className="btn btn-magic" disabled={!usable.length} onClick={ctx.analyze}><Play size={15} />{project.analysis ? '再解析' : '解析を実行'}</button>
              </div>
            )}
          </motion.div>
        </motion.div>

        <motion.div className="col gap-16" variants={stagger} initial="hidden" animate="show">
          {!hasReply && (
            <motion.div className="card ai-card" variants={fadeUp}>
              <div className="card-head"><h3><span className="magic-text">AI</span> 読解を体験</h3></div>
              <div className="card-body col gap-12">
                <div className="small text-2">
                  顧客から届いた<b>文章だけの回答メール</b>を追加します。表や項目名がないためルールでは読めませんが、
                  AI が「保護等級は IP4X」「50Hz は誤記」を読み取り、根拠の文を示します。
                </div>
                <button className="btn btn-magic" onClick={() => act(() => api.addSample(project.id, 'reply'), '顧客回答メールを追加しました。再解析してください')}>
                  <MailPlus size={16} />顧客回答メールを追加
                </button>
              </div>
            </motion.div>
          )}
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>デモ用サンプル資料</h3></div>
            <div className="card-body col gap-12">
              <div className="small text-2">架空の制御盤案件の資料です。ダウンロードして左の枠にドロップすると、取込から試せます。</div>
              {SAMPLES.map((s) => (
                <a key={s} className="row small" href={`/api/samples/${encodeURIComponent(s)}`} download>
                  <Download size={14} /><span className="ellipsis">{s}</span>
                </a>
              ))}
            </div>
          </motion.div>
          <motion.div className="card" variants={fadeUp}>
            <div className="card-head"><h3>取込時の自動チェック</h3></div>
            <div className="card-body col gap-8 small text-2">
              {['重複資料（内容のハッシュで判定）', '破損・パスワード保護ファイル', '画像だけの PDF は AI-OCR で文字・寸法を読取', '表紙から資料名・版・発行日・種別を推定', '折り返された文を段落にまとめて AI へ渡す'].map((t) => (
                <div key={t} className="row"><CheckCircle2 size={14} color="var(--ok)" />{t}</div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>
      {del && (
        <Modal title="資料を削除しますか？" onClose={() => setDel(null)}
          footer={<><button className="btn" onClick={() => setDel(null)}>キャンセル</button>
            <button className="btn btn-danger" onClick={async () => { await act(() => api.deleteDoc(project.id, del.id), '資料を削除しました'); setDel(null) }}><Trash2 size={15} />削除</button></>}>
          「{del.filename}」を案件から削除します。解析結果は再解析時に更新されます。
        </Modal>
      )}
    </div>
  )
}
