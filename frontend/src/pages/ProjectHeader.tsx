import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion'
import { Building2, CalendarClock, Check, ChevronRight, Play, RefreshCw, Sparkles } from 'lucide-react'
import type { Project } from '../types'
import { STEPS, stepStates } from '../steps'
import { dateOnly, dueInfo, initials } from '../ui'

function StepBadge({ project, sid }: { project: Project; sid: string }) {
  const a = project.analysis
  if (!a) return null
  if (sid === 'review') {
    const blocking = a.issues.some((i) => i.blocking && i.target?.kind === 'field')
    const r = a.issues.filter((i) => i.target?.kind === 'field' || i.target?.kind === 'component').length
    return r ? <span className={`step-badge ${blocking ? 'red' : 'amber'}`}>{r}</span> : <span className="step-badge green">OK</span>
  }
  if (sid === 'fit') {
    const v = a.fit.verdict
    return <span className={`step-badge ${v === 'ok' ? 'green' : v === 'ng' ? 'red' : 'amber'}`}>{v === 'ok' ? '可' : v === 'ng' ? '不可' : '不足'}</span>
  }
  if (sid === 'estimate') {
    const n = a.estimate.rfq.length + a.estimate.expired.length
    return n ? <span className="step-badge amber">{n}</span> : null
  }
  if (sid === 'output' && project.approval?.status === 'approved') return <span className="step-badge green">承認済</span>
  return null
}

export default function ProjectHeader({ project, tab, go, onAnalyze, needsAnalysis }: {
  project: Project; tab: string; go: (t: string) => void; onAnalyze: () => void; needsAnalysis: boolean
}) {
  const a = project.analysis
  const states = stepStates(project)
  const step = STEPS.find((s) => s.id === tab) ?? STEPS[0]
  const due = dueInfo(project.due_date)

  // マウス位置に合わせて透かし文字と光をわずかに動かす（奥行きのある視差）
  const mx = useMotionValue(0)
  const my = useMotionValue(0)
  const sx = useSpring(mx, { stiffness: 60, damping: 18 })
  const sy = useSpring(my, { stiffness: 60, damping: 18 })
  const wmX = useTransform(sx, (v) => v * 36)
  const wmY = useTransform(sy, (v) => v * 18)
  const glowX = useTransform(sx, (v) => v * -60)

  return (
    <div className="project-head" onMouseMove={(e) => {
      const r = e.currentTarget.getBoundingClientRect()
      mx.set((e.clientX - r.left) / r.width - 0.5)
      my.set((e.clientY - r.top) / r.height - 0.5)
    }} onMouseLeave={() => { mx.set(0); my.set(0) }}>
      <div className="ph-aurora" aria-hidden>
        <motion.span className="g1" style={{ x: glowX }} /><span className="g2" /><span className="g3" />
      </div>
      <motion.div className="ph-watermark" aria-hidden style={{ x: wmX, y: wmY }}>
        <motion.span key={step.id} initial={{ opacity: 0, scale: 1.35, rotate: -8, filter: 'blur(8px)' }}
          animate={{ opacity: 1, scale: 1, rotate: 0, filter: 'blur(0px)' }} transition={{ type: 'spring', stiffness: 160, damping: 18 }}>
          {step.kanji}
        </motion.span>
      </motion.div>

      <div className="crumbs">
        <a href="#/">見積案件</a><ChevronRight size={12} /><span className="ph-qno">{project.quote_no}</span>
      </div>
      <div className="project-title">
        <motion.h1 key={project.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
          {project.name}
        </motion.h1>
        <motion.span className={`ph-status s-${project.status}`} key={project.status} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 420, damping: 18 }}>
          <i />{project.status}
        </motion.span>
        {a?.ai.used && (
          <motion.span className="ph-ai badge-ai" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 420, damping: 18, delay: 0.08 }}>
            <Sparkles size={11} />AI 読解済み
          </motion.span>
        )}
        <span className="spacer" />
        <div className="ph-meta">
          {project.customer && (
            <div className="ph-chip" title={`顧客：${project.customer}`}>
              <span className="ph-chip-ic"><Building2 size={14} /></span>
              <span className="ph-chip-tx"><small>顧客</small><b>{project.customer}</b></span>
            </div>
          )}
          {project.due_date && (
            <div className={`ph-chip due ${due?.tone ?? ''}`} title="見積の提出期限">
              <span className="ph-chip-ic"><CalendarClock size={14} /></span>
              <span className="ph-chip-tx"><small>提出期限</small><b>{dateOnly(project.due_date)}</b></span>
              {due && <span className="due-count">{due.label}</span>}
            </div>
          )}
          <div className="ph-chip" title={`担当：${project.owner}`}>
            <span className="ph-avatar">{initials(project.owner || '担当')}</span>
            <span className="ph-chip-tx"><small>担当</small><b>{project.owner}</b></span>
          </div>
        </div>
        {project.documents.length > 0 && (
          <button className={`btn btn-sm ph-analyze ${needsAnalysis ? 'btn-magic' : 'btn-glass'}`} onClick={onAnalyze}>
            {a ? <RefreshCw size={14} /> : <Play size={14} />}{a ? '再解析' : '解析を実行'}
          </button>
        )}
      </div>

      <nav className="steps" aria-label="工程">
        {STEPS.map((s, i) => {
          const st = states[s.id]
          const active = tab === s.id
          return (
            <motion.button key={s.id} className={`step ${active ? 'active' : ''} ${st ? `st-${st}` : ''}`} onClick={() => go(s.id)}
              aria-current={active ? 'page' : undefined}
              initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 + i * 0.045, type: 'spring', stiffness: 300, damping: 24 }}>
              {active && (
                <motion.span layoutId="step-active" className="step-active-bg" transition={{ type: 'spring', stiffness: 400, damping: 34 }}>
                  <span className="step-active-line" />
                </motion.span>
              )}
              {i < 5
                ? <span className="step-num">{st === 'done' ? <Check size={12} strokeWidth={3.4} /> : i + 1}</span>
                : <span className="step-num icon"><s.icon size={13} /></span>}
              <span>{s.label}</span>
              <StepBadge project={project} sid={s.id} />
            </motion.button>
          )
        })}
      </nav>
    </div>
  )
}
