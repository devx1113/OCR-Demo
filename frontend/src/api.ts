import type {
  AccuracyReport, AiStats, AiStatus, AiUsage, EffectReport, FitReport, ImpactResult, LearningResult, MasterSaveResult, MasterVersion,
  OcrResult, Perm, Project, ProjectSummary, RevisionDiff, SimilarResult, UserInfo,
} from './types'

export const USERS: UserInfo[] = [
  { name: '山田 太郎', role: '設計担当', perms: ['edit', 'request', 'export', 'draft'] },
  { name: '佐藤 花子', role: '設計課長', perms: ['edit', 'request', 'approve', 'export', 'draft', 'master'] },
  { name: '鈴木 一郎', role: '営業担当', perms: ['export'] },
]

/** 現在の担当者が権限を持つか（画面の出し分け用。最終的な判定はサーバー側で行う） */
export function can(perm: Perm, name = currentUser()): boolean {
  const u = USERS.find((x) => x.name === name)
  return !u || u.perms.includes(perm)
}

// 案件ごとに、画面が最後に受け取った更新番号。更新系の要求に添えて送り、
// 他の担当者が先に更新していた場合はサーバーが 409（code: stale）で知らせる
const seenRev = new Map<string, number>()
export const rememberRev = (p: { id?: string; rev?: number } | null | undefined) => {
  if (p?.id && typeof p.rev === 'number') seenRev.set(p.id, p.rev)
}

export function currentUser(): string {
  try {
    return localStorage.getItem('user') || USERS[0].name
  } catch {
    return USERS[0].name
  }
}

export function setCurrentUser(name: string) {
  try {
    localStorage.setItem('user', name)
  } catch {
    /* プライベートモード等では保存しない */
  }
}

export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

async function request<T>(method: string, url: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { 'X-User': encodeURIComponent(currentUser()) }
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  const pid = /^\/api\/projects\/([0-9a-f]{12})/.exec(url)?.[1]
  if (pid && method !== 'GET' && seenRev.has(pid)) headers['X-Project-Rev'] = String(seenRev.get(pid))
  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'サーバーに接続できません。アプリが起動しているか確認してください。', null)
  }
  // AI の呼び出し結果を画面左下の接続表示に反映する（502 = OpenAI 側の失敗）
  if (/\/ai(\/|\?|$)/.test(url) && method !== 'GET') {
    window.dispatchEvent(new CustomEvent('ai-health', { detail: res.status === 502 ? 'error' : res.ok ? 'ok' : null }))
  }
  if (!res.ok) {
    let data: unknown = null
    try {
      data = await res.json()
    } catch {
      /* JSON 以外のエラー本文 */
    }
    const detail = (data as { detail?: unknown })?.detail
    throw new ApiError(res.status, typeof detail === 'string' ? detail : `エラーが発生しました（${res.status}）`, data)
  }
  const data = await res.json()
  if (data && typeof data === 'object' && 'quote_no' in data) rememberRev(data as Project)
  return data as T
}

const P = (id: string) => `/api/projects/${id}`

export const api = {
  health: () => request<{ ok: boolean; pdf_preview: boolean; ai: AiStatus }>('GET', '/api/health'),
  projects: () => request<ProjectSummary[]>('GET', '/api/projects'),
  createProject: (b: { name: string; customer?: string; due_date?: string }) => request<Project>('POST', '/api/projects', b),
  createDemo: () => request<Project>('POST', '/api/projects/demo?analyze=false'),
  addSample: (id: string, kind: string) => request<Project>('POST', `${P(id)}/samples/${kind}`),
  project: (id: string) => request<Project>('GET', P(id)),
  updateProject: (id: string, b: Partial<Project>) => request<Project>('PATCH', P(id), b),
  deleteProject: (id: string) => request<{ ok: boolean }>('DELETE', P(id)),
  upload: (id: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Project>('POST', `${P(id)}/documents`, fd, true)
  },
  updateDoc: (id: string, did: string, b: Record<string, unknown>) => request<Project>('PATCH', `${P(id)}/documents/${did}`, b),
  deleteDoc: (id: string, did: string) => request<Project>('DELETE', `${P(id)}/documents/${did}`),
  docFileUrl: (id: string, did: string) => `${P(id)}/documents/${did}/file`,
  parsed: (id: string, did: string) => request<import('./types').Parsed>('GET', `${P(id)}/documents/${did}/parsed`),
  analyze: (id: string) => request<Project>('POST', `${P(id)}/analyze`),
  fieldAction: (id: string, key: string, b: { action: string; value?: string; choice?: number; reason?: string }) =>
    request<Project>('POST', `${P(id)}/fields/${key}`, b),
  fieldReset: (id: string, key: string) => request<Project>('DELETE', `${P(id)}/fields/${key}`),
  componentAction: (id: string, key: string, b: Record<string, unknown>) => request<Project>('POST', `${P(id)}/components/${key}`, b),
  componentReset: (id: string, key: string) => request<Project>('DELETE', `${P(id)}/components/${key}`),
  componentAdd: (id: string, b: Record<string, unknown>) => request<Project>('POST', `${P(id)}/components`, b),
  settings: (id: string, b: Record<string, unknown>) => request<Project>('PATCH', `${P(id)}/settings`, b),
  lineEdit: (id: string, lid: string, b: { qty?: number; unit_cost?: number }) => request<Project>('POST', `${P(id)}/estimate/lines/${lid}`, b),
  lineReset: (id: string, lid: string) => request<Project>('DELETE', `${P(id)}/estimate/lines/${lid}`),
  addQuestion: (id: string, b: { question: string; item?: string; category?: string }) => request<Project>('POST', `${P(id)}/questions`, b),
  deleteQuestion: (id: string, qid: string) => request<Project>('DELETE', `${P(id)}/questions/${qid}`),
  approve: (id: string, comment: string) => request<Project>('POST', `${P(id)}/approve`, { comment }),
  requestApproval: (id: string, comment: string) => request<Project>('POST', `${P(id)}/approval/request`, { comment }),
  returnApproval: (id: string, comment: string) => request<Project>('POST', `${P(id)}/approval/return`, { comment }),
  compareRevisions: (id: string, a: number | string, b: number | string) =>
    request<RevisionDiff>('GET', `${P(id)}/revisions/compare?a=${a}&b=${b}`),
  rev: (id: string) => request<{ rev: number; modified_by: string; updated_at: string }>('GET', `${P(id)}/rev`),
  users: () => request<UserInfo[]>('GET', '/api/users'),
  accuracy: () => request<AccuracyReport>('GET', '/api/report/accuracy'),
  ocrResult: (id: string, did: string) => request<OcrResult | null>('GET', `${P(id)}/documents/${did}/ocr`),
  unapprove: (id: string) => request<Project>('POST', `${P(id)}/unapprove`),
  aiRead: (id: string, did: string, force = false) =>
    request<{ stats: AiStats; usage: AiUsage; cached: boolean; model: string; at: string; kind?: 'ocr' }>('POST', `${P(id)}/documents/${did}/ai${force ? '?force=true' : ''}`),
  aiAsk: (id: string, question: string) => request<Project>('POST', `${P(id)}/ai/ask`, { question }),
  aiChatClear: (id: string) => request<Project>('DELETE', `${P(id)}/ai/chat`),
  aiReview: (id: string) => request<Project>('POST', `${P(id)}/ai/review`),
  aiEmail: (id: string, kind: 'quote' | 'questions') => request<{ subject: string; body: string; usage: AiUsage }>('POST', `${P(id)}/ai/email`, { kind }),
  aiSettings: () => request<AiStatus>('GET', '/api/ai/settings'),
  saveAiSettings: (b: Partial<AiStatus>) => request<AiStatus>('PUT', '/api/ai/settings', b),
  aiTest: () => request<{ reply: string; usage: AiUsage }>('POST', '/api/ai/test'),
  master: <T,>(name: string) => request<T>('GET', `/api/master/${name}`),
  saveMaster: (name: string, data: unknown, recompute = false) =>
    request<MasterSaveResult>('PUT', `/api/master/${name}${recompute ? '?recompute=true' : ''}`, data),
  masterImpact: (name: string, data: unknown) => request<ImpactResult>('POST', `/api/master/${name}/impact`, data),
  masterVersions: (name: string) => request<MasterVersion[]>('GET', `/api/master/${name}/versions`),
  restoreMaster: (name: string, version: number, recompute = false) =>
    request<MasterSaveResult>('POST', `/api/master/${name}/versions/${version}/restore${recompute ? '?recompute=true' : ''}`),
  similar: (id: string, limit = 5) => request<SimilarResult>('GET', `${P(id)}/similar?limit=${limit}`),
  fitReview: (id: string, b: { decision: 'agree' | 'disagree'; final_verdict?: string; final_enclosure?: string; reason?: string }) =>
    request<Project>('POST', `${P(id)}/fit/review`, b),
  fitReviewReset: (id: string) => request<Project>('DELETE', `${P(id)}/fit/review`),
  learning: () => request<LearningResult>('GET', '/api/learning'),
  learningDecide: (cid: string, action: 'apply' | 'dismiss') =>
    request<MasterSaveResult & { master?: string }>('POST', `/api/learning/${cid}/${action}`),
  fitReport: () => request<FitReport>('GET', '/api/report/fit'),
  effectReport: () => request<EffectReport>('GET', '/api/report/effect'),
  regression: () => request<ImpactResult>('GET', '/api/report/regression'),
}

/** 出力ファイルを取得する。409（未解決事項あり）は ApiError として返す。 */
export async function fetchExport(id: string, kind: string, force = false): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${P(id)}/export/${kind}${force ? '?force=true' : ''}`, {
    headers: { 'X-User': encodeURIComponent(currentUser()) },
  })
  if (!res.ok) {
    let data: unknown = null
    try {
      data = await res.json()
    } catch {
      /* noop */
    }
    const detail = (data as { detail?: unknown })?.detail
    throw new ApiError(res.status, typeof detail === 'string' ? detail : `出力に失敗しました（${res.status}）`, data)
  }
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd)
  return { blob: await res.blob(), filename: m ? decodeURIComponent(m[1]) : `${kind}${kind.endsWith('csv') ? '.csv' : '.xlsx'}` }
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
