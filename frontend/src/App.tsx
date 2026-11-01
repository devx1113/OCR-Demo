import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api, currentUser } from './api'
import type { AiStatus, Project } from './types'
import Dashboard from './pages/Dashboard'
import ProjectPage from './pages/ProjectPage'
import Sidebar from './Sidebar'
import MasterPage from './pages/MasterPage'
import ReportPage from './pages/ReportPage'

export type Route =
  | { page: 'dashboard' }
  | { page: 'project'; id: string; tab: string }
  | { page: 'master'; tab: string }
  | { page: 'report'; tab: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'projects' && parts[1]) return { page: 'project', id: parts[1], tab: parts[2] || 'documents' }
  if (parts[0] === 'master') return { page: 'master', tab: parts[1] || 'parts' }
  if (parts[0] === 'report') return { page: 'report', tab: parts[1] || 'accuracy' }
  return { page: 'dashboard' }
}

export function navigate(path: string) {
  window.location.hash = path
}

export const UserCtx = createContext<string>(currentUser())
export const useUser = () => useContext(UserCtx)
export const ProjectCtx = createContext<(p: Project | null) => void>(() => {})
const OFF: AiStatus = { configured: false, enabled: false, model: '', review_model: '' }
export const AiCtx = createContext<{ ai: AiStatus; refreshAi: () => void }>({ ai: OFF, refreshAi: () => {} })
export const useAi = () => useContext(AiCtx)

export default function App() {
  const [route, setRoute] = useState<Route>(parse(window.location.hash))
  const [user, setUser] = useState(currentUser())
  const [project, setProject] = useState<Project | null>(null)
  const [ai, setAi] = useState<AiStatus>(OFF)

  const refreshAi = useCallback(() => { api.health().then((h) => setAi(h.ai)).catch(() => setAi(OFF)) }, [])
  useEffect(() => { refreshAi() }, [refreshAi])
  const [aiFault, setAiFault] = useState(false)
  useEffect(() => {
    const h = (e: Event) => { const d = (e as CustomEvent).detail; if (d) setAiFault(d === 'error') }
    window.addEventListener('ai-health', h)
    return () => window.removeEventListener('ai-health', h)
  }, [])
  useEffect(() => {
    const h = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  useEffect(() => {
    if (route.page !== 'project') setProject(null)
  }, [route.page])

  const pageKey = route.page === 'project' ? `p-${route.id}` : route.page

  return (
    <AiCtx.Provider value={{ ai, refreshAi }}>
      <UserCtx.Provider value={user}>
        <ProjectCtx.Provider value={setProject}>
          <div className="app">
            <Sidebar route={route} project={project} ai={ai} aiFault={aiFault} user={user} onUser={setUser} />
            <main className="main">
              <motion.div key={pageKey} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}
                initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
                {route.page === 'dashboard' && <Dashboard />}
                {route.page === 'project' && <ProjectPage id={route.id} tab={route.tab} />}
                {route.page === 'master' && <MasterPage tab={route.tab} />}
                {route.page === 'report' && <ReportPage tab={route.tab} />}
              </motion.div>
            </main>
          </div>
        </ProjectCtx.Provider>
      </UserCtx.Provider>
    </AiCtx.Provider>
  )
}
