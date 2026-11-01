export type Source = {
  doc_id: string
  doc_name: string
  page: number | null
  bbox: number[] | null
  ids: string[]
  text: string
}

export type FieldStatus =
  | 'ok' | 'confirmed' | 'edited' | 'resolved' | 'changed'
  | 'review' | 'inferred' | 'conflict' | 'missing' | 'asked' | 'empty'

export type Candidate = {
  value: string
  methods?: string[]
  raw: string
  sources: Source[]
  doc_name: string
  doc_date: string
  doc_role: string
}

export type Field = {
  key: string
  label: string
  group: 'project' | 'panel' | 'conditions'
  type: string
  required: boolean
  options?: string[] | null
  value: string
  raw: string
  status: FieldStatus
  confidence: number
  sources: Source[]
  candidates: Candidate[]
  provisional?: number
  change: null | {
    from: string; to: string; desc: string; reason: string; source: Source; before_matches: boolean
  }
  note: string
  methods: string[]
  ai_alt: { value: string; source: Source }[]
  original?: string
  override?: { action: string; by: string; at: string; reason?: string }
}

export type Component = {
  key: string
  no: number | null
  name: string
  raw_name: string
  name_note: string
  aliased: boolean
  raw_model: string
  model: string
  spec: string
  qty: number | null
  mount: string | null
  layout_mount: string | null
  confidence: number
  sources: Source[]
  origin: 'main' | 'added' | 'manual' | 'recommended' | 'ai'
  ai_verified?: boolean
  doc_name: string
  changes: { attr: string; from: unknown; to: unknown; reason: string; source: Source; before_matches: boolean }[]
  notes: string[]
  in_master: boolean
  master_match: null | { model: string; name: string; kind: 'exact' | 'normalized' | 'fuzzy'; score: number }
  w?: number; h?: number; d?: number
  heat_w?: number
  price?: number | null
  price_valid_until?: string | null
  category?: string
  maker?: string
  clearance?: { top?: number; bottom?: number; side?: number }
  status: 'ok' | 'confirmed' | 'review' | 'no_master' | 'changed' | 'added' | 'deleted' | 'recommended' | 'ai'
  deleted?: boolean
  recommended?: boolean
  override?: { qty?: number; model?: string; deleted?: boolean; confirmed?: boolean }
}

export type Check = {
  id: string
  label: string
  status: 'ok' | 'ng' | 'warn' | 'na'
  detail: string
  rule?: string
  value?: number
  limit?: number
}

export type Enclosure = {
  id: string | null
  name: string
  type?: string
  w: number; h: number; d: number
  base_h: number
  plate_w: number; plate_h: number
  inner_d: number
  price: number | null
  price_valid_until?: string
  from_spec?: boolean
  plate_from_spec?: boolean
}

export type PlacedItem = {
  key: string; name: string; model: string; category: string; terminal?: boolean
  x: number; y: number; w: number; h: number
  fx?: number; fy?: number; fw?: number; fh?: number
  clearance?: boolean
  recommended?: boolean
}

export type Plate = {
  plate_w: number; plate_h: number; usable_w: number; used_h: number
  rows: { y: number; h: number; used_w: number; kind: string }[]
  items: PlacedItem[]
  ducts: { x: number; y: number; w: number; h: number }[]
  oversized: { name: string; model: string; fw: number; fh: number }[]
  occupancy: number
  area_ratio: number
  n_horizontal_ducts: number
}

export type Thermal = {
  heat_w: number; area_m2: number; k: number; ambient: number; ambient_from_spec: boolean
  max_internal: number; allow_dt: number; dt: number; internal_temp: number
  need_fan: boolean; required_airflow: number
  fan: null | { model: string; name: string; airflow: number; w: number; h: number }
  formula_area: string; formula_dt: string; formula_airflow: string
}

export type Fit = {
  verdict: 'ok' | 'ng' | 'insufficient'
  checks: Check[]
  plate: Plate | null
  door: null | { door_w: number; door_h: number; used_h: number; items: PlacedItem[]; fits: boolean }
  enclosure: Enclosure | null
  thermal: Thermal | null
  alternatives: { id: string; name: string; w: number; h: number; d: number; price: number; occupancy: number; is_current: boolean }[]
  spec_enclosure: Enclosure | null
  spec_result: null | { verdict: Fit['verdict']; occupancy: number; used_h: number; plate_h: number }
  selected_id: string | null
}

export type EstimateLine = {
  id: string
  group: string
  name: string
  spec: string
  qty: number
  unit: string
  unit_cost: number | null
  cost: number
  source: string
  flags: string[]
  note: string
  base_unit_cost?: number
}

export type MarketInfo = {
  steel: number; fx: number; steel_index: number; steel_index_base: number; usd_jpy: number; usd_jpy_base: number
  delta: number; lines: number
}

export type Estimate = {
  lines: EstimateLine[]
  groups: Record<string, string>
  customer_lines: { id: string; name: string; qty: number; unit: string; unit_price: number; amount: number; cost: number }[]
  cost_total: number
  margin: number
  sale_total: number
  discount: number
  tax: number
  grand_total: number
  profit: number
  profit_rate: number
  rfq: EstimateLine[]
  expired: EstimateLine[]
  tax_rate: number
  market?: MarketInfo
}

export type Issue = {
  id: string
  severity: 'high' | 'medium' | 'low'
  type: string
  blocking?: boolean
  title: string
  detail: string
  target: null | { kind: 'field' | 'component' | 'fit' | 'estimate' | 'document'; key?: string }
}

export type Question = {
  no: number
  category: string
  item: string
  question: string
  refs: string[]
  key: string | null
  custom_id?: string
  assumption?: string
}

export type Risk = { label: string; impact: string; text: string; source: Source }

export type Analysis = {
  fields: Field[]
  components: Component[]
  fit: Fit
  estimate: Estimate
  issues: Issue[]
  questions: Question[]
  conditions: string[]
  risks: Risk[]
  instructions: { section: string; text: string; source: Source }[]
  stats: { fields_found: number; fields_total: number; components: number; auto_ok: number; blocking: number; issues: number; documents: number }
  timings: { stage: string; ms: number }[]
  analyzed_at: string
  ai: AiSummary
  ai_notes: { summary: string; source: Source; doc_name: string }[]
  drawings?: DrawingCheck[]
}

/** AI-OCR で読んだ図面の寸法と、仕様（変更連絡反映後）との照合 */
export type DrawingCheck = {
  doc_id: string
  doc_name: string
  title: string
  drawing_no: string
  scale: string
  doc_kind: string | null
  lines: number
  model: string
  items: { axis: 'w' | 'h' | 'd'; label: string; drawing: number; spec: number | null; match: boolean; matches_before: boolean; source: Source }[]
  mismatch: DrawingCheck['items']
}

export type OcrResult = {
  kind: 'ocr'
  model: string
  at: string
  doc_kind: string
  title?: string
  drawing_no?: string
  scale?: string
  lines: { id: string; text: string; page: number }[]
  dimensions: { axis: string; value_mm: number | null; text: string; verified: boolean; source: Source }[]
  rejected: unknown[]
  stats: AiStats
  usage: AiUsage
}

export type AiUsage = { model: string; seconds: number; input_tokens: number; output_tokens: number; recheck?: string[] }

export type AiSummary = {
  used: boolean
  docs: { doc_id: string; filename: string; model: string; at: string; stats: AiStats; usage: AiUsage }[]
  verified: number
  rejected: number
  agreed: number
  ai_only: number
}

export type AiStats = { fields: number; components: number; corrections: number; rejected: number; lines?: number; dimensions?: number; pages?: number }

export type AiStatus = { configured: boolean; enabled: boolean; model: string; review_model: string; models?: string[] }

export type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  at: string
  user?: string
  citations?: Source[]
  unverified?: number
  usage?: AiUsage
}

export type AiReview = {
  summary: string
  findings: { severity: 'high' | 'medium' | 'low'; category: string; title: string; detail: string; target_key: string }[]
  usage: AiUsage
  at: string
  analyzed_at: string
}

export type Doc = {
  id: string
  filename: string
  ext: string
  kind: string
  size: number
  pages: number | null
  text_layer: boolean
  status: 'ok' | 'warning' | 'error'
  messages: string[]
  role: 'main' | 'supplement' | 'drawing' | 'other'
  received_date: string | null
  version: string | null
  title: string | null
  doc_no: string | null
  include: boolean
  uploaded_at: string
  uploaded_by: string
  blocks?: number
  tables?: number
}

export type ApprovalStatus = 'requested' | 'approved' | 'returned' | 'revoked' | 'withdrawn'

export type Approval = {
  status: ApprovalStatus
  by: string
  at: string
  comment?: string
  sale_total?: number
  rev?: number
  requested_by?: string | null
  requested_at?: string | null
}

export type Revision = {
  rev: number
  at: string
  approved_by: string
  requested_by?: string | null
  comment?: string
  sale_total: number
  tax: number
  grand_total: number
  cost_total: number
  margin: number
  profit_rate: number
  enclosure: string | null
  lines: { name: string; qty: number; unit: string; unit_price: number; amount: number }[]
  fields: Record<string, string>
  components: { name: string; model: string; qty: number | null }[]
  conditions: string[]
  questions: number
}

type Delta<T> = { a: T; b: T; delta: number }
export type RevisionDiff = {
  a: { rev: number | string; at: string; approved_by?: string }
  b: { rev: number | string; at: string; approved_by?: string }
  totals: { sale_total: Delta<number>; cost_total: Delta<number>; grand_total: Delta<number>; margin: Delta<number> }
  lines: { name: string; kind: 'added' | 'removed' | 'changed'; a?: Revision['lines'][number]; b?: Revision['lines'][number]; delta?: number }[]
  fields: { label: string; a: string | null; b: string | null }[]
  components: { name: string; kind: 'added' | 'removed' | 'changed'; a?: Revision['components'][number]; b?: Revision['components'][number] }[]
  conditions: { added: string[]; removed: string[] }
  other: { label: string; a: string | null; b: string | null }[]
  changes: number
}

export type Perm = 'edit' | 'request' | 'approve' | 'export' | 'draft' | 'master'
export type UserInfo = { name: string; role: string; perms: Perm[] }

export type AccuracyReport = {
  projects: number
  fields: { auto: number; confirmed: number; corrected: number; resolved: number; open: number; filled: number; rate: number | null; reviewed_rate: number | null }
  by_method: { method: 'both' | 'rule' | 'ai'; label: string; n: number; ok: number; corrected: number; rate: number | null }[]
  by_field: { key: string; label: string; auto: number; confirmed: number; corrected: number; resolved: number; open: number; projects: number; rate: number | null }[]
  components: { auto?: number; confirmed?: number; corrected?: number; deleted?: number; manual?: number; rate: number | null }
  ai: { verified?: number; rejected?: number; agreed?: number; ai_only?: number; ocr_docs?: number; ocr_dims?: number }
  detect: { conflicts?: number; changes?: number; missing?: number; drawing_mismatch?: number }
  rows: { id: string; quote_no: string; name: string; documents: number; extracted: number; confirmed: number; corrected: number; open: number; rate: number | null; analyzed_at: string }[]
}

export type HistoryEntry = { at: string; user: string; action: string; detail: string }

export type Project = {
  id: string
  quote_no: string
  name: string
  customer: string
  owner: string
  due_date: string | null
  created_at: string
  updated_at: string
  status: string
  documents: Doc[]
  history: HistoryEntry[]
  settings: { enclosure_id?: string | null; include_fan?: boolean; margin?: number; ai?: boolean; line_overrides?: Record<string, { qty?: number; unit_cost?: number }> }
  analysis?: Analysis
  analysis_stale?: boolean
  approval?: Approval
  revisions?: Revision[]
  rev?: number
  modified_by?: string
  exported_at?: string
  custom_questions?: { id: string; question: string; item: string; category: string; by: string }[]
  chat?: ChatMessage[]
  ai_review?: AiReview
  fit_review?: FitReview
}

export type FitReview = {
  decision: 'agree' | 'disagree'; by: string; at: string; reason: string
  system: { verdict: string; enclosure: string | null; enclosure_id: string | null }
  final_verdict: 'ok' | 'ng' | string; final_enclosure: string | null
}

export type SimilarCase = {
  source: 'archive' | 'system'; project_id?: string; quote_no: string; name: string; customer: string; date: string | null
  result: string | null; designer: string | null; note: string; enclosure: string | null; sale_total: number | null; cost_total: number | null
  score: number; breakdown: { key: string; label: string; weight: number; value: number }[]; match: string[]; diff: string[]
}

export type SimilarResult = {
  items: SimilarCase[]; searched: number
  price: { n: number; min: number; max: number; avg: number; current: number; delta_rate: number; position: 'low' | 'high' | 'within' } | null
  sizes: { enclosure: string; n: number }[]; won: number; lost: number
  current: { enclosure: string | null; sale_total: number; drive_kw: number; components: number }
}

export type ImpactChange = { kind: string; label: string; a: string | number | null; b: string | number | null; delta?: number; severity: 'high' | 'medium' | 'low' }
export type ImpactRow = {
  id: string; quote_no: string; name: string; customer: string; approval: string | null; locked: boolean; changed: boolean
  changes: ImpactChange[]; analyzed_at?: string
  before: { verdict: string; enclosure: string | null; sale_total: number | null }; after: { verdict: string; enclosure: string | null; sale_total: number | null }
}
export type ImpactResult = {
  total: number; changed: number; skipped: number; verdict_changed: number; locked_changed: number; sale_delta: number
  rows: ImpactRow[]; summary?: string
}

export type MasterVersion = { version: number; at: string; by: string; summary: string }
export type MasterSaveResult = { ok: boolean; by: string; version: number; recomputed: { id: string; quote_no: string; name: string }[] }

export type LearningCandidate = {
  id: string; kind: 'part_alias' | 'name_alias' | 'field_alias' | 'unregistered' | 'frequent_edit'; kind_ja: string
  target: string; target_label?: string; value: string; title: string; effect: string; applicable: boolean; count: number
  projects: { id: string; quote_no: string; name: string }[]; examples: string[]
}
export type LearningResult = {
  items: LearningCandidate[]; open: number; applied: number
  decisions: { id: string; at: string; by: string; title: string; kind?: string; action: 'applied' | 'dismissed' }[]
}

export type FitReport = {
  recorded: number; agree: number; disagree: number; rate: number | null; verdict_diff: number; enclosure_diff: number
  rows: { id: string; quote_no: string; name: string; decision: 'agree' | 'disagree'; system_verdict: string; system_enclosure: string | null
    final_verdict: string; final_enclosure: string | null; reason: string; by: string; at: string }[]
}

export type EffectReport = {
  baseline_hours: number; idle_minutes: number; completed: number; projects: number; avg_active_min: number | null
  saved_hours_total: number | null; reduction_rate: number | null; correction_rate: number | null; avg_analysis_sec: number | null
  rows: { id: string; quote_no: string; name: string; completed: boolean; active_min: number; lead_hours: number | null; events: number
    analysis_ms: number; corrected: number; fields: number; saved_hours: number | null }[]
}

export type ProjectSummary = {
  id: string
  quote_no: string
  name: string
  customer: string
  owner: string
  due_date: string | null
  created_at: string
  updated_at: string
  status: string
  documents: number
  stats: Analysis['stats'] | null
  verdict: Fit['verdict'] | null
  sale_total: number | null
  approval: { status: ApprovalStatus; by: string; at: string; comment?: string } | null
  revisions: number
  modified_by: string
}

export type Parsed = {
  format: 'pdf' | 'docx' | 'xlsx'
  pages: { w: number; h: number }[]
  blocks: (
    | { id: string; type: 'para'; page: number | null; bbox: number[] | null; text: string; style?: string; size?: number }
    | { id: string; type: 'table'; page: number | null; bbox: number[] | null; rows: { id: string; text: string; bbox: number[] | null }[][] }
  )[]
}
