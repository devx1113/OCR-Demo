import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle, Check, ChevronRight, Eye, Play, RefreshCw, ScanLine, Sparkles, UsersRound,
} from 'lucide-react'
import { ApiError, api, can, currentUser } from '../api'
import { ProjectCtx, navigate, useAi, useUser } from '../App'
import type { AiStats, Doc, Project } from '../types'
import { Badge, CountUp, Sakura, Spinner, fadeUp, stagger, useToast } from '../ui'
import DocumentsTab from './DocumentsTab'
import ReviewTab from './ReviewTab'
import FitTab from './FitTab'
import EstimateTab from './EstimateTab'
import OutputTab from './OutputTab'
import HistoryTab from './HistoryTab'
import ProjectHeader from './ProjectHeader'


export type Focus = { kind: string; key?: string } | null

export type Ctx = {
  project: Project
  act: (fn: () => Promise<Project>, success?: string) => Promise<boolean>
  analyze: () => void
  go: (tab: string, focus?: Focus) => void
  focus: Focus
}

const STAGES = ['資料の構造化（文字・表・座標）', 'ルール抽出と AI 読解の突き合わせ', '資料間照合（矛盾・変更・記載漏れ）', '部品マスタ照合', '収容判定・温度計算', '見積計算', '要確認・質疑書の生成']
type DocRun = { doc: Doc; state: 'waiting' | 'reading' | 'done' | 'error' | 'skipped'; stats?: AiStats; seconds?: number; cached?: boolean; error?: string; started?: number }

function DocSheet({ run, now }: { run: DocRun; now: number }) {
  const kind = run.doc.ext.replace('.', '')
  const reading = run.state === 'reading'
  return (
    <motion.div className="doc-sheet" variants={fadeUp} layout data-testid="doc-sheet">
      {reading && <div className="scan-beam" />}
      <div className="row" style={{ position: 'relative' }}>
        <div className={`file-icon ${kind}`} style={{ width: 34, height: 40, fontSize: 8, paddingBottom: 5 }}>{run.doc.text_layer ? kind.toUpperCase() : <ScanLine size={14} />}</div>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="bold ellipsis small">{run.doc.filename}</div>
          <div className="xs muted">
            {run.state === 'waiting' && '待機中'}
            {reading && <>{run.doc.text_layer ? 'AI が読解中…' : 'AI-OCR で画像から文字・寸法を読取中…'} {((now - (run.started || now)) / 1000).toFixed(1)} 秒</>}
            {run.state === 'done' && run.stats && (run.stats.lines != null
              ? <>文字 {run.stats.lines}行・寸法 {run.stats.dimensions}件{run.cached ? '（前回の読取結果）' : ` ・ ${run.seconds}秒`}</>
              : <>項目 {run.stats.fields}・機器 {run.stats.components}・訂正 {run.stats.corrections}{run.cached ? '（前回の読解結果）' : ` ・ ${run.seconds}秒`}</>)}
            {run.state === 'skipped' && 'ルール抽出のみ'}
            {run.state === 'error' && <span style={{ color: 'var(--danger)' }}>{run.error}</span>}
          </div>
        </div>
        {run.state === 'done' && <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="check-icon" style={{ background: 'var(--grad-ok)' }}><Check size={14} /></motion.div>}
        {reading && <Spinner size={18} />}
        {run.state === 'error' && <AlertTriangle size={18} color="var(--danger)" />}
      </div>
      <div className="lines" style={{ marginTop: 8 }}>{[92, 78, 85, 60].map((w, i) => <i key={i} style={{ width: `${w}%` }} />)}</div>
    </motion.div>
  )
}

function AnalyzeStage({ project, onDone, onClose }: { project: Project; onDone: (p: Project) => void; onClose: () => void }) {
  const toast = useToast()
  const { ai } = useAi()
  const useAiNow = ai.enabled && project.settings?.ai !== false
  // 文字のある資料は AI 読解、スキャン図面（画像PDF）は AI-OCR の対象
  const targets = project.documents.filter((d) => d.status !== 'error' && d.include && (d.text_layer || (useAiNow && d.ext === '.pdf')))
  const [runs, setRuns] = useState<DocRun[]>(targets.map((d) => ({ doc: d, state: useAiNow ? 'waiting' : 'skipped' })))
  const [step, setStep] = useState(-1)
  const [result, setResult] = useState<Project | null>(null)
  const [now, setNow] = useState(Date.now())
  const started = useRef(Date.now())
  const finished = useRef<number | null>(null)

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    let alive = true
    const upd = (id: string, patch: Partial<DocRun>) => alive && setRuns((rs) => rs.map((r) => (r.doc.id === id ? { ...r, ...patch } : r)))
    const run = async () => {
      setStep(0)
      if (useAiNow) {
        await Promise.all(targets.map(async (d, i) => {
          await new Promise((r) => setTimeout(r, i * 180))
          upd(d.id, { state: 'reading', started: Date.now() })
          try {
            const r = await api.aiRead(project.id, d.id)
            upd(d.id, { state: 'done', stats: r.stats, seconds: r.usage.seconds, cached: r.cached })
          } catch (e) {
            upd(d.id, { state: 'error', error: (e as Error).message.slice(0, 80) })
          }
        }))
      }
      let s = 1
      const timer = setInterval(() => alive && setStep(Math.min(s++, STAGES.length - 1)), 260)
      try {
        const p = await api.analyze(project.id)
        await new Promise((r) => setTimeout(r, 260 * STAGES.length))
        clearInterval(timer)
        if (!alive) return
        finished.current = Date.now()
        setStep(STAGES.length)
        setResult(p)
      } catch (e) {
        clearInterval(timer)
        toast((e as Error).message, 'error')
        onClose()
      }
    }
    run()
    return () => { alive = false }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const a = result?.analysis
  const elapsed = ((finished.current ?? now) - started.current) / 1000
  return (
    <motion.div className="analyze-stage" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} role="dialog" aria-label="解析の進捗">
      <motion.div className="orb" style={{ width: 300, height: 300, left: '8%', top: '12%', background: 'radial-gradient(circle, rgba(109,132,255,.35), transparent 70%)' }}
        animate={{ y: [0, 30, 0], x: [0, 20, 0] }} transition={{ duration: 9, repeat: Infinity }} />
      <motion.div className="orb" style={{ width: 360, height: 360, right: '6%', bottom: '6%', background: 'radial-gradient(circle, rgba(255,92,157,.28), transparent 70%)' }}
        animate={{ y: [0, -30, 0], x: [0, -20, 0] }} transition={{ duration: 11, repeat: Infinity }} />
      <div className="analyze-inner">
        <div>
          <div className="row" style={{ marginBottom: 14 }}>
            <Badge cls={useAiNow ? 'badge-ai' : 'badge-glass'}>{useAiNow ? <><Sparkles size={11} />AI 読解 {ai.model}</> : 'ルール抽出のみ'}</Badge>
            <span className="xs" style={{ color: '#9aa4cf' }}>経過 {elapsed.toFixed(1)} 秒</span>
          </div>
          <motion.div className="col gap-12" variants={stagger} initial="hidden" animate="show">
            {runs.map((r) => <DocSheet key={r.doc.id} run={r} now={now} />)}
            {runs.length === 0 && <div className="small" style={{ color: '#b8c2ea' }}>文字を読み取れる資料がありません</div>}
          </motion.div>
        </div>
        <div>
          <motion.div className="analyze-title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            {result ? <span className="gold-text">解析完了</span> : '資料を読み解いています'}
          </motion.div>
          <div className="small" style={{ color: '#aab3dc', margin: '6px 0 18px' }}>
            {result ? `処理時間 ${elapsed.toFixed(1)} 秒` : useAiNow ? 'AI の読み取り結果は、引用が原文に存在するかを一件ずつ照合します' : '辞書とルールで項目を抽出しています'}
          </div>
          {!a && (
            <div className="pipe">
              {STAGES.map((s, i) => {
                const state = i < step ? 'done' : i === step ? 'running' : ''
                return (
                  <motion.div key={s} className={`pipe-step ${state}`} initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}>
                    <div className="pipe-icon">{state === 'done' ? <Check size={14} /> : state === 'running' ? <Spinner size={12} /> : null}</div>
                    <span className="grow">{s}</span>
                    {i === 0 && step === 0 && useAiNow && <span className="xs" style={{ color: '#ffb3cf' }}>AI 読解 {runs.filter((r) => r.state === 'done').length}/{runs.length}</span>}
                  </motion.div>
                )
              })}
            </div>
          )}
          {a && (
            <motion.div variants={stagger} initial="hidden" animate="show">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                {[
                  { v: a.stats.fields_found, l: `抽出項目（全 ${a.stats.fields_total}）` },
                  { v: a.stats.components, l: '構成機器' },
                  { v: a.ai.used ? a.ai.agreed : a.stats.auto_ok, l: a.ai.used ? 'ルール×AI 一致' : '自動で整合' },
                  { v: a.stats.issues, l: `要確認（承認前に解決 ${a.stats.blocking}）` },
                ].map((s) => (
                  <motion.div key={s.l} className="big-stat" variants={fadeUp}>
                    <div className="v"><CountUp value={s.v} /></div>
                    <div className="l">{s.l}</div>
                  </motion.div>
                ))}
              </div>
              {a.ai.used && (
                <motion.div variants={fadeUp} className="small mt-12" style={{ color: '#d9cfff' }}>
                  AI が読み取った {a.ai.verified} 件はすべて原文と照合済み。{a.ai.rejected ? `根拠を確認できなかった ${a.ai.rejected} 件は不採用にしました。` : ''}
                  {a.ai.ai_only ? `ルールでは拾えなかった値を ${a.ai.ai_only} 件、AI が補いました。` : ''}
                </motion.div>
              )}
              <motion.div variants={fadeUp} className="row mt-24">
                <button className="btn btn-lg btn-magic" onClick={() => onDone(result!)} autoFocus>抽出結果を確認する<ChevronRight size={18} /></button>
              </motion.div>
            </motion.div>
          )}
        </div>
      </div>
      {result && <Sakura count={26} />}
    </motion.div>
  )
}

export default function ProjectPage({ id, tab }: { id: string; tab: string }) {
  const toast = useToast()
  const setGlobal = useContext(ProjectCtx)
  useUser() // 担当者を切り替えたら権限表示を更新する
  const [project, setProject] = useState<Project | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [focus, setFocus] = useState<Focus>(null)
  const [remote, setRemote] = useState<{ modified_by: string; updated_at: string } | null>(null)

  useEffect(() => {
    api.project(id).then((p) => {
      setProject(p)
      try {
        if (sessionStorage.getItem(`autorun:${id}`)) {
          sessionStorage.removeItem(`autorun:${id}`)
          setAnalyzing(true)
        }
      } catch { /* noop */ }
    }).catch((e) => setError(e.message))
  }, [id])
  useEffect(() => { setGlobal(project) }, [project, setGlobal])

  const reload = useCallback(() => api.project(id).then((p) => { setProject(p); setRemote(null) }).catch(() => {}), [id])
  const act = useCallback(async (fn: () => Promise<Project>, success?: string) => {
    try {
      const p = await fn()
      setProject(p)
      setRemote(null)
      if (success) toast(success, 'success')
      return true
    } catch (e) {
      // 他の担当者が先に更新していた → 最新の内容を読み込んでから、もう一度操作してもらう
      if (e instanceof ApiError && (e.data as { code?: string })?.code === 'stale') {
        await reload()
        toast(e.message, 'info')
        return false
      }
      toast((e as Error).message, 'error')
      return false
    }
  }, [toast, reload])

  // 他の担当者による更新に気付けるよう、更新番号を定期的に確認する（20〜30名での同時利用を想定）
  const revRef = useRef(0)
  useEffect(() => { revRef.current = project?.rev ?? 0 }, [project?.rev])
  useEffect(() => {
    const t = setInterval(() => {
      if (document.hidden) return
      api.rev(id).then((r) => {
        if (r.rev > revRef.current && r.modified_by && r.modified_by !== currentUser()) setRemote(r)
      }).catch(() => {})
    }, 8000)
    return () => clearInterval(t)
  }, [id])

  const go = useCallback((t: string, f?: Focus) => {
    setFocus(f ?? null)
    navigate(`/projects/${id}/${t}`)
  }, [id])

  if (error) return <div className="page"><div className="banner banner-red">{error}</div></div>
  if (!project) return <div className="page"><div className="skeleton" style={{ height: 140 }} /></div>

  const a = project.analysis
  const ctx: Ctx = { project, act, analyze: () => setAnalyzing(true), go, focus }
  const needsAnalysis = !a || project.analysis_stale
  const tabNeedsAnalysis = ['review', 'fit', 'estimate', 'output'].includes(tab) && !a

  return (
    <>
      <ProjectHeader project={project} tab={tab} go={go} onAnalyze={() => setAnalyzing(true)} needsAnalysis={!!needsAnalysis} />
      <AnimatePresence>
        {remote && (
          <motion.div className="live-banner" initial={{ opacity: 0, y: -10, height: 0 }} animate={{ opacity: 1, y: 0, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <span className="live-banner-ic"><UsersRound size={15} /></span>
            <span className="grow"><b>{remote.modified_by}</b> さんがこの案件を更新しました（{remote.updated_at.slice(11, 16)}）。最新の内容を表示してから操作してください。</span>
            <button className="btn btn-sm btn-primary" onClick={reload}><RefreshCw size={13} />最新の内容を表示</button>
          </motion.div>
        )}
      </AnimatePresence>
      {!can('edit') && (
        <div className="banner banner-blue readonly-banner"><Eye size={16} />
          <span className="grow">閲覧モード：{currentUser()}（営業担当）は抽出値・見積の編集や承認はできません。承認済みの見積書・質疑書の出力と、AI への質問は利用できます。</span>
        </div>
      )}
      {project.analysis_stale && tab !== 'documents' && (
        <div className="banner banner-amber" style={{ margin: '12px 30px 0' }}>
          <RefreshCw size={16} /><span className="grow">資料または AI 読解結果が更新されています。最新の内容で再解析してください（担当者の修正内容は保持されます）。</span>
          <button className="btn btn-sm btn-primary" onClick={() => setAnalyzing(true)}>再解析</button>
        </div>
      )}
      {/* 画面切替は入場アニメーションのみ（退場アニメーションの入れ子待ちで切替が止まるのを避ける） */}
      <motion.div key={tab} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}
        initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          {tabNeedsAnalysis ? (
            <div className="page"><div className="card"><div className="empty">
              <div className="empty-icon"><Play size={26} /></div><h3>まだ解析されていません</h3>
              <div>資料を登録して「解析を実行」を押してください。</div>
              <button className="btn btn-primary mt-16" onClick={() => go('documents')}>資料の登録へ</button>
            </div></div></div>
          ) : (
            <>
              {tab === 'documents' && <DocumentsTab ctx={ctx} />}
              {tab === 'review' && <ReviewTab ctx={ctx} />}
              {tab === 'fit' && <FitTab ctx={ctx} />}
              {tab === 'estimate' && <EstimateTab ctx={ctx} />}
              {tab === 'output' && <OutputTab ctx={ctx} />}
              {tab === 'history' && <HistoryTab ctx={ctx} />}
            </>
          )}
      </motion.div>
      <AnimatePresence>
        {analyzing && (
          <AnalyzeStage project={project} onClose={() => setAnalyzing(false)}
            onDone={(p) => { setProject(p); setAnalyzing(false); go('review') }} />
        )}
      </AnimatePresence>
    </>
  )
}
