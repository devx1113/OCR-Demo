import { Calculator, FileSpreadsheet, FileStack, History, LayoutPanelTop, ListChecks } from 'lucide-react'
import type { Project } from './types'

/** 案件画面の工程（ヘッダのタブとサイドバーで共通）。kanji は工程を表す一字（ヘッダの透かし文字） */
export const STEPS = [
  { id: 'documents', label: '資料', icon: FileStack, kanji: '資' },
  { id: 'review', label: '抽出・確認', icon: ListChecks, kanji: '確' },
  { id: 'fit', label: '収容判定', icon: LayoutPanelTop, kanji: '収' },
  { id: 'estimate', label: '見積', icon: Calculator, kanji: '積' },
  { id: 'output', label: '出力・承認', icon: FileSpreadsheet, kanji: '承' },
  { id: 'history', label: '履歴', icon: History, kanji: '歴' },
]

export type StepState = 'done' | 'alert' | 'warn' | 'todo'

/** 案件の各工程が「済・要対応・未着手」のどれかを、解析結果から判定する */
export function stepStates(p: Project): Record<string, StepState> {
  const a = p.analysis
  if (!a || p.analysis_stale) return { documents: p.documents.length ? 'done' : 'todo', review: 'todo', fit: 'todo', estimate: 'todo', output: 'todo' }
  const blockingReview = a.issues.some((i) => i.blocking && (i.target?.kind === 'field' || i.target?.kind === 'component'))
  return {
    documents: 'done',
    review: blockingReview ? 'alert' : 'done',
    fit: a.fit.verdict === 'ok' ? 'done' : 'alert',
    estimate: a.estimate.rfq.length + a.estimate.expired.length ? 'warn' : 'done',
    output: p.approval?.status === 'approved' ? 'done' : 'todo',
  }
}
