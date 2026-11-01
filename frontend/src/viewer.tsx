import { useEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { FileText, Minus, Plus, ScanLine } from 'lucide-react'
import { api } from './api'
import type { Doc, Parsed, Source } from './types'
import { Spinner } from './ui'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

type HL = { page: number | null; bbox: number[] | null; ids: string[]; primary: boolean }

function PdfPage({ doc, pageNo, scale, highlights }: { doc: PDFDocumentProxy; pageNo: number; scale: number; highlights: HL[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [page, setPage] = useState<PDFPageProxy | null>(null)
  useEffect(() => {
    let alive = true
    doc.getPage(pageNo).then((p) => alive && setPage(p))
    return () => { alive = false }
  }, [doc, pageNo])
  useEffect(() => {
    if (!page || !canvasRef.current) return
    const vp = page.getViewport({ scale })
    const dpr = window.devicePixelRatio || 1
    const c = canvasRef.current
    c.width = Math.floor(vp.width * dpr)
    c.height = Math.floor(vp.height * dpr)
    c.style.width = `${vp.width}px`
    c.style.height = `${vp.height}px`
    const ctx = c.getContext('2d')!
    let task: RenderTask | null = page.render({ canvasContext: ctx, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined })
    task.promise.catch(() => {}).finally(() => { task = null })
    return () => { task?.cancel() }
  }, [page, scale])
  const vp = page?.getViewport({ scale })
  return (
    <div className="pdf-page" style={{ width: vp?.width ?? 595 * scale, height: vp?.height ?? 842 * scale }}>
      <canvas ref={canvasRef} />
      <span className="pdf-page-num">p.{pageNo}</span>
      {highlights.filter((h) => h.page === pageNo && h.bbox).map((h, i) => {
        const [x0, y0, x1, y1] = h.bbox!
        const pad = 3
        return (
          <div key={`${i}-${x0}-${y0}`} className={`hl ${h.primary ? 'primary' : 'secondary'}`} data-primary={h.primary ? '1' : undefined}
            style={{ left: x0 * scale - pad, top: y0 * scale - pad, width: (x1 - x0) * scale + pad * 2, height: (y1 - y0) * scale + pad * 2 }} />
        )
      })}
    </div>
  )
}

function PdfView({ url, scale, highlights, focusKey }: { url: string; scale: number; highlights: HL[]; focusKey: string }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState<string | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    setDoc(null)
    setError(null)
    const task = pdfjs.getDocument({ url })
    task.promise.then(setDoc, (e) => setError(String(e?.message || e)))
    return () => { task.destroy() }
  }, [url])
  useEffect(() => {
    if (!doc) return
    const t = setTimeout(() => {
      const el = wrap.current?.querySelector('[data-primary="1"]')
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 120)
    return () => clearTimeout(t)
  }, [doc, focusKey, scale])
  if (error) return <div className="empty">PDFを表示できません：{error}</div>
  if (!doc) return <div className="empty"><Spinner size={22} /></div>
  return (
    <div ref={wrap}>
      {Array.from({ length: doc.numPages }, (_, i) => (
        <PdfPage key={i} doc={doc} pageNo={i + 1} scale={scale} highlights={highlights} />
      ))}
    </div>
  )
}

function BlocksView({ parsed, highlights, focusKey, doc }: { parsed: Parsed; highlights: HL[]; focusKey: string; doc: Doc }) {
  const wrap = useRef<HTMLDivElement>(null)
  const ids = useMemo(() => new Set(highlights.flatMap((h) => h.ids)), [highlights])
  useEffect(() => {
    const t = setTimeout(() => {
      wrap.current?.querySelector('.hl-block')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 120)
    return () => clearTimeout(t)
  }, [focusKey, parsed])
  return (
    <div ref={wrap}>
      <div className="doc-banner"><FileText size={14} />{doc.ext === '.xlsx' ? 'Excel' : 'Word'} 文書の構造化表示（段落・表を抽出した結果）</div>
      <div className="docview">
        {parsed.blocks.map((b) => {
          if (b.type === 'para') {
            const cls = b.style === 'title' ? 'dv-title' : b.style === 'heading' ? 'dv-heading' : ''
            return <p key={b.id} className={`${cls} ${ids.has(b.id) ? 'hl-block' : ''}`}>{b.text}</p>
          }
          return (
            <table key={b.id}>
              <tbody>
                {b.rows.map((row, ri) => {
                  const rowHit = row.length > 0 && row.every((c) => ids.has(c.id))
                  return (
                    <tr key={ri} className={rowHit ? 'hl-block' : ''}>
                      {row.map((c) => (
                        <td key={c.id} className={!rowHit && ids.has(c.id) ? 'hl-block' : ''} style={ri === 0 ? { fontWeight: 700, background: '#f3f5f9' } : undefined}>{c.text}</td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
        })}
      </div>
    </div>
  )
}

/** 原文ビューア。focus の資料を開き、出典位置をハイライトしてスクロールする。 */
export function SourceViewer({ projectId, docs, focus, related }: {
  projectId: string; docs: Doc[]; focus: Source | null; related: Source[]
}) {
  const viewable = docs.filter((d) => d.status !== 'error')
  const [active, setActive] = useState<string | null>(viewable[0]?.id ?? null)
  const [scale, setScale] = useState(1.25)
  const [parsed, setParsed] = useState<Record<string, Parsed>>({})
  useEffect(() => {
    if (focus?.doc_id) setActive(focus.doc_id)
  }, [focus])
  useEffect(() => {
    if (!active && viewable[0]) setActive(viewable[0].id)
  }, [active, viewable])
  const doc = viewable.find((d) => d.id === active) || null
  useEffect(() => {
    if (doc && doc.ext !== '.pdf' && !parsed[doc.id]) {
      api.parsed(projectId, doc.id).then((p) => setParsed((s) => ({ ...s, [doc.id]: p }))).catch(() => {})
    }
  }, [doc, projectId, parsed])

  const highlights: HL[] = useMemo(() => {
    const all = [...(focus ? [focus] : []), ...related.filter((r) => r !== focus)]
    return all.filter((s) => s.doc_id === active).map((s) => ({ page: s.page, bbox: s.bbox, ids: s.ids, primary: s === focus }))
  }, [focus, related, active])
  const focusKey = focus ? `${focus.doc_id}:${focus.ids.join(',')}` : ''

  return (
    <div className="viewer">
      <div className="viewer-bar">
        <div className="tabs" style={{ overflowX: 'auto', maxWidth: '75%' }}>
          {viewable.map((d) => (
            <button key={d.id} className={`tab ${d.id === active ? 'active' : ''}`} onClick={() => setActive(d.id)} title={d.filename}>
              {d.text_layer ? <FileText size={13} /> : <ScanLine size={13} />}
              <span className="ellipsis" style={{ maxWidth: 200 }}>{d.filename}</span>
            </button>
          ))}
        </div>
        <span className="spacer" />
        {doc?.ext === '.pdf' && (
          <div className="row gap-4">
            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setScale((s) => Math.max(0.6, +(s - 0.15).toFixed(2)))} aria-label="縮小"><Minus size={14} /></button>
            <span className="small num" style={{ width: 42, textAlign: 'center' }}>{Math.round(scale * 100)}%</span>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setScale((s) => Math.min(2.5, +(s + 0.15).toFixed(2)))} aria-label="拡大"><Plus size={14} /></button>
          </div>
        )}
      </div>
      <div className="viewer-scroll">
        {!doc && <div className="empty">表示できる資料がありません</div>}
        {doc && doc.ext === '.pdf' && (
          <>
            {!doc.text_layer && (
              <div className="banner banner-amber" style={{ maxWidth: 760, margin: '0 auto 14px' }}>
                <ScanLine size={16} />画像のみの PDF です。AI-OCR で読み取った寸法注記を選ぶと、図面上の位置を枠で示します（位置は目安）。
              </div>
            )}
            <PdfView url={api.docFileUrl(projectId, doc.id)} scale={scale} highlights={highlights} focusKey={focusKey} />
          </>
        )}
        {doc && doc.ext !== '.pdf' && (parsed[doc.id]
          ? <BlocksView parsed={parsed[doc.id]} highlights={highlights} focusKey={focusKey} doc={doc} />
          : <div className="empty"><Spinner size={22} /></div>)}
      </div>
    </div>
  )
}

/** 任意の PDF（Blob URL など）を表示するだけのビューア。 */
export function PlainPdf({ url, scale = 1.1 }: { url: string; scale?: number }) {
  return <PdfView url={url} scale={scale} highlights={[]} focusKey="" />
}
