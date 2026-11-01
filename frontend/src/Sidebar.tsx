import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Check, ChevronsUpDown, FolderKanban, Gauge, Sparkles } from 'lucide-react'
import { USERS, api, setCurrentUser } from './api'
import type { AiStatus, Project, ProjectSummary } from './types'
import { initials } from './ui'
import { STEPS, stepStates, type StepState } from './steps'
import type { Route } from './App'

type Count = { n: number; alert?: boolean }

const go = (path: string) => { window.location.hash = path }

const permHint = (p: string[]) =>
  p.includes('approve') ? '編集・承認・マスタ変更' : p.includes('edit') ? '編集・承認依頼' : '閲覧・承認済み見積の出力'


/** マウス位置に光が追従するナビ項目（--mx / --my を CSS のスポットライトに渡す） */
function NavItem({ active, onClick, icon, label, sub, count, node, index = 0 }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; label: string; sub?: boolean; count?: Count; node?: StepState; index?: number
}) {
  return (
    <motion.button
      className={`nav-item ${sub ? 'nav-sub' : ''} ${active ? 'active' : ''}`} onClick={onClick} title={label} aria-label={label}
      aria-current={active ? 'page' : undefined}
      initial={{ opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.08 + index * 0.05, type: 'spring', stiffness: 260, damping: 24 }}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
        e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
      }}>
      {active && (
        <motion.span layoutId={sub ? 'nav-active-sub' : 'nav-active'} className="nav-active-bg" transition={{ type: 'spring', stiffness: 380, damping: 32 }}>
          <span className="nav-active-shine" />
        </motion.span>
      )}
      {node && (
        <span className={`step-node ${node} ${active ? 'current' : ''}`} aria-hidden>
          {node === 'done' ? <Check size={9} strokeWidth={4} /> : node === 'alert' || node === 'warn' ? '!' : null}
        </span>
      )}
      <span className="nav-icon">{icon}</span>
      <span className="nav-text">{label}</span>
      {count && count.n > 0 && (
        <motion.span key={count.n} className={`count ${count.alert ? 'alert' : ''}`} initial={{ scale: 0.4 }} animate={{ scale: 1 }}
          transition={{ type: 'spring', stiffness: 500, damping: 18 }}>{count.n}</motion.span>
      )}
    </motion.button>
  )
}

function LiveBars() {
  return <span className="live-bars" aria-hidden><i /><i /><i /><i /></span>
}

// 帯の中をゆっくり舞う花びら（位置・速さは固定値にして再描画で変わらないようにする）
const PETALS = [
  { left: 12, delay: 0, dur: 17, size: 9 }, { left: 64, delay: 4, dur: 21, size: 7 }, { left: 38, delay: 9, dur: 19, size: 10 },
  { left: 82, delay: 13, dur: 23, size: 8 }, { left: 24, delay: 16, dur: 18, size: 6 }, { left: 52, delay: 6.5, dur: 25, size: 8 },
]

export default function Sidebar({ route, project, ai, aiFault, user, onUser }: {
  route: Route; project: Project | null; ai: AiStatus; aiFault: boolean; user: string; onUser: (name: string) => void
}) {
  const [menu, setMenu] = useState(false)
  const [recent, setRecent] = useState<ProjectSummary[]>([])
  // 案件画面以外では「最近の案件」を表示する（画面を移るたびに最新化）
  useEffect(() => {
    if (route.page === 'project') return
    let alive = true
    api.projects().then((ps) => alive && setRecent([...ps].sort((x, y) => (y.updated_at || '').localeCompare(x.updated_at || '')).slice(0, 4))).catch(() => {})
    return () => { alive = false }
  }, [route])
  const me = USERS.find((u) => u.name === user) || USERS[0]
  const a = project?.analysis
  const counts: Record<string, Count | undefined> = a ? {
    review: { n: a.issues.filter((i) => i.target?.kind === 'field' || i.target?.kind === 'component').length, alert: a.issues.some((i) => i.blocking && i.target?.kind === 'field') },
    fit: a.fit.verdict === 'ok' ? undefined : { n: 1, alert: true },
    estimate: { n: a.estimate.rfq.length + a.estimate.expired.length },
  } : {}
  const flow = STEPS.filter((s) => s.id !== 'history')
  const history = STEPS.find((s) => s.id === 'history')!
  const tab = route.page === 'project' ? route.tab : ''
  const activeIdx = flow.findIndex((s) => s.id === tab)
  const states = project ? stepStates(project) : {}
  const fields = a?.fields ?? []
  const settled = fields.filter((f) => ['ok', 'confirmed', 'edited', 'resolved', 'changed'].includes(f.status)).length
  const relevant = fields.filter((f) => f.status !== 'empty').length
  const progress = relevant ? settled / relevant : 0
  const aiState = !ai.enabled ? 'off' : aiFault ? 'fault' : 'on'

  return (
    <aside className="sidebar">
      <div className="sb-aurora" aria-hidden><span className="a1" /><span className="a2" /><span className="a3" /></div>
      <div className="sb-edge" aria-hidden />
      <div className="sb-petals" aria-hidden>
        {PETALS.map((p, i) => (
          <span key={i} style={{ left: `${p.left}%`, width: p.size, height: p.size * 0.78, animationDelay: `${p.delay}s`, animationDuration: `${p.dur}s` }} />
        ))}
      </div>

      <div className="brand">
        <motion.div className="brand-mark-wrap" initial={{ scale: 1.9, rotate: -14, opacity: 0 }} animate={{ scale: 1, rotate: 0, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 320, damping: 16, delay: 0.1 }}>
          <span className="brand-ring" aria-hidden />
          <div className="brand-mark">盤</div>
        </motion.div>
        <motion.div className="brand-text" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.35, duration: 0.5 }}>
          <div className="brand-name">盤見積アシスタント</div>
          <div className="brand-sub">PANEL ESTIMATE AI</div>
        </motion.div>
      </div>

      <NavItem index={0} active={route.page === 'dashboard'} onClick={() => go('/')} icon={<FolderKanban size={16} />} label="見積案件" />
      <NavItem index={1} active={route.page === 'report'} onClick={() => go('/report')} icon={<Gauge size={16} />} label="精度・効果レポート" />
      <NavItem index={2} active={route.page === 'master'} onClick={() => go('/master')} icon={<BookOpen size={16} />} label="マスタ・設定" />

      {route.page !== 'project' && recent.length > 0 && (
        <motion.div className="sb-recent" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25, duration: 0.4 }}>
          <div className="nav-label"><span className="hishi" />最近の案件</div>
          {recent.map((r, i) => (
            <motion.button key={r.id} className="recent-item" onClick={() => go(`/projects/${r.id}/review`)} title={`${r.name}（${r.status}）`}
              initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.3 + i * 0.06 }}>
              <span className={`recent-dot s-${r.status}`} />
              <span className="recent-body">
                <span className="recent-name">{r.name}</span>
                <span className="recent-meta">{r.quote_no}<i>{r.status}</i></span>
              </span>
            </motion.button>
          ))}
        </motion.div>
      )}

      {/* 退場アニメーションは付けない（画面遷移が重なると退場が完了せず、透明な要素が残るため） */}
      {route.page === 'project' && project && (
        <motion.div key={project.id} className="sb-project" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="nav-label"><span className="hishi" />現在の案件</div>
          <div className="project-chip" title={project.name}>
            <div className="pc-name ellipsis">{project.name}</div>
            <div className="pc-meta">
              <span className="pc-no">{project.quote_no}</span>
              <span className={`pc-status s-${project.status}`}>{project.status}</span>
            </div>
            {a && (
              <div className="pc-progress" title={`確認の進捗：${settled} / ${relevant} 項目が確定・整合`}>
                <div className="pc-bar"><motion.span initial={{ width: 0 }} animate={{ width: `${progress * 100}%` }} transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }} /></div>
                <span className="pc-pct">{Math.round(progress * 100)}<small>%</small></span>
              </div>
            )}
          </div>

          <div className="stepper">
            <div className="stepper-rail" aria-hidden>
              <motion.span className="stepper-fill" initial={false}
                animate={{ height: `${activeIdx < 0 ? 100 : (activeIdx / (flow.length - 1)) * 100}%` }}
                transition={{ type: 'spring', stiffness: 120, damping: 20 }} />
            </div>
            {flow.map((s, i) => (
              <NavItem key={s.id} index={i + 2} sub node={states[s.id] ?? 'todo'} active={tab === s.id} count={counts[s.id]}
                onClick={() => go(`/projects/${project.id}/${s.id}`)} icon={<s.icon size={15} />} label={s.label} />
            ))}
          </div>
          <div className="sb-divider" />
          <NavItem index={8} sub active={tab === 'history'} onClick={() => go(`/projects/${project.id}/history`)} icon={<history.icon size={15} />} label={history.label} />
        </motion.div>
      )}

      <div className="sidebar-foot">
        <div className={`ai-pill ${aiState === 'off' ? 'off' : aiState === 'fault' ? 'fault' : ''}`}
          title={aiState === 'off' ? 'AI は無効です（ルール抽出のみ）' : aiState === 'fault' ? '直前の AI 呼び出しに失敗しました（AI 以外の機能は使えます）' : 'OpenAI API に接続中'}>
          {aiState === 'on' ? <LiveBars /> : <span className="live-dot" />}
          <Sparkles size={13} className="ai-spark" />
          <span className="grow">{aiState === 'off' ? 'AI 未接続（ルールのみ）' : aiState === 'fault' ? <>AI 接続エラー <b>{ai.model}</b></> : <>AI 接続中 <b>{ai.model}</b></>}</span>
        </div>
        <div className="user-box" onClick={() => setMenu((m) => !m)} title={`${me.name}（${me.role}）`}>
          <div className="avatar-wrap"><span className="avatar-ring" aria-hidden /><div className="avatar">{initials(me.name)}</div></div>
          <div className="grow user-text">
            <div className="user-name">{me.name}</div>
            <div className="user-role">{me.role}</div>
          </div>
          <ChevronsUpDown size={14} className="user-chevron" />
          <AnimatePresence>
            {menu && (
              <motion.div className="user-menu" onClick={(e) => e.stopPropagation()}
                initial={{ opacity: 0, y: 8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.97 }}>
                <div className="xs muted" style={{ padding: '4px 8px' }}>担当者を切り替え（デモ用）</div>
                {USERS.map((u) => (
                  <button key={u.name} onClick={() => { setCurrentUser(u.name); onUser(u.name); setMenu(false) }}>
                    <div className="avatar" style={{ width: 28, height: 28, fontSize: 12 }}>{initials(u.name)}</div>
                    <div><div className="small bold">{u.name}</div><div className="xs muted">{u.role}・{permHint(u.perms)}</div></div>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="version"><span className="hishi sm" />DEMO v1.0 ・ 藍彩エディション</div>
      </div>
    </aside>
  )
}
