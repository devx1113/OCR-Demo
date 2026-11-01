import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertCircle, ArrowRight, BadgeCheck, Bot, ClipboardList, Clock, FilePlus2, FileSearch, FolderOpen, Inbox, MailCheck, ScanSearch, Sparkles, Trash2, Undo2, Wallet,
} from 'lucide-react'
import { api, can } from '../api'
import { navigate, useAi, useUser } from '../App'
import type { ProjectSummary } from '../types'
import NewProjectDialog from './NewProjectDialog'
import { Badge, CountUp, Empty, Hanko, Modal, PROJECT_STATUS, Spinner, VERDICT, dateOnly, dt, fadeUp, stagger, useToast, wareki, yen } from '../ui'

const FLOW = [
  { kanji: '取', title: '資料の取込', desc: 'PDF・Word・Excel を一括登録。破損・重複・画像PDFを自動検知', color: '#3d55e6' },
  { kanji: '読', title: 'AI 読解と照合', desc: 'ルール抽出と AI 読解を突き合わせ、出典付きで矛盾・変更・記載漏れを検出', color: '#7b4dff' },
  { kanji: '判', title: '収容判定', desc: 'クリアランス込みで配置を計算し、可否・根拠・代替筐体・放熱を提示', color: '#ea4b2a' },
  { kanji: '算', title: '見積計算', desc: 'マスタと工数式で原価を積上げ、利益率を調整して売価を算出', color: '#c9972e' },
  { kanji: '出', title: '承認・出力', desc: '既存の Excel 雛形へ転記。質疑書・根拠書・送付メールも作成', color: '#0c8f62' },
]

const AI_FEATURES = [
  { icon: ScanSearch, title: 'AI 読解', desc: '文章で書かれた要望（メール・議事録）からも値を読み取り、引用が原文にあるかを機械的に検証' },
  { icon: Bot, title: '仕様書に質問', desc: '「立会検査は何回？」と聞くと、根拠の箇所をハイライトして回答' },
  { icon: FileSearch, title: 'AI 設計レビュー', desc: 'ベテラン設計者の観点で、容量・保護協調・放熱・見積漏れを指摘' },
  { icon: MailCheck, title: '送付メール作成', desc: '見積提出・質疑確認のメール文案を、日本のビジネス敬語で作成' },
]

export default function Dashboard() {
  const toast = useToast()
  const { ai } = useAi()
  const [items, setItems] = useState<ProjectSummary[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [demoBusy, setDemoBusy] = useState(false)
  const [confirmDel, setConfirmDel] = useState<ProjectSummary | null>(null)

  const load = () => api.projects().then(setItems).catch((e) => toast(e.message, 'error'))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const createDemo = async () => {
    setDemoBusy(true)
    try {
      const p = await api.createDemo()
      try { sessionStorage.setItem(`autorun:${p.id}`, '1') } catch { /* 保存できなくても手動で解析できる */ }
      navigate(`/projects/${p.id}/documents`)
    } catch (e) {
      toast((e as Error).message, 'error')
      setDemoBusy(false)
    }
  }

  const remove = async (p: ProjectSummary) => {
    await api.deleteProject(p.id)
    setConfirmDel(null)
    toast(`${p.quote_no} を削除しました`)
    load()
  }

  const user = useUser()
  const list = items || []
  // 担当者ごとの「やること」：課長は承認待ち、担当は差し戻された案件
  const inbox = can('approve', user)
    ? list.filter((p) => p.approval?.status === 'requested').map((p) => ({ p, kind: 'requested' as const }))
    : can('request', user) ? list.filter((p) => p.approval?.status === 'returned').map((p) => ({ p, kind: 'returned' as const })) : []
  const open = list.filter((p) => !['承認済', '出力済'].includes(p.status))
  const waiting = list.filter((p) => p.status === '承認待ち').length
  const issues = list.reduce((s, p) => s + (p.stats?.blocking || 0), 0)
  const done = list.filter((p) => ['承認済', '出力済'].includes(p.status)).length
  const total = list.reduce((s, p) => s + (p.sale_total || 0), 0)
  const kpis = [
    { label: '進行中の案件', value: open.length, sub: `全 ${list.length} 件`, icon: ClipboardList, bg: 'var(--grad-ai)', glow: 'rgba(61,85,230,.10)', fmt: (n: number) => `${n}` },
    { label: '未解決の要確認事項', value: issues, sub: '承認前に解決が必要', icon: AlertCircle, bg: 'var(--grad-shu)', glow: 'rgba(234,75,42,.10)', fmt: (n: number) => `${n}` },
    { label: '承認済み', value: done, sub: waiting ? `承認待ち ${waiting} 件` : '見積書を出力できます', icon: BadgeCheck, bg: 'var(--grad-ok)', glow: 'rgba(12,143,98,.10)', fmt: (n: number) => `${n}` },
    { label: '見積総額（税抜）', value: total, sub: '解析済み案件の合計', icon: Wallet, bg: 'linear-gradient(120deg,#e6b64c,#b8862a)', glow: 'rgba(212,166,74,.14)', fmt: yen },
  ]

  return (
    <div className="page">
      <div className="page-narrow">
        <motion.section className="hero-banner" initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}>
          <div className="hero-content">
            <div className="hero-vertical">見積を、確かに。</div>
            <div className="grow">
              <motion.div className="hero-date" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}>{wareki()}</motion.div>
              <motion.h1 className="hero-title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                仕様書から見積書まで、<span className="gold-text">根拠とともに。</span>
              </motion.h1>
              <motion.div className="hero-lead" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.45 }}>
                AI とルールの二重チェックで仕様を読み取り、収容判定・見積・Excel 出力までを一気通貫で支援します。
                すべての値に「どの資料のどこに書いてあるか」を添えて、最終判断は設計者が行います。
              </motion.div>
              <motion.div className="row mt-16" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6 }}>
                <button className="btn btn-lg btn-magic" onClick={createDemo} disabled={demoBusy} data-testid="demo-button">
                  {demoBusy ? <Spinner /> : <Sparkles size={18} />}デモ案件で体験する
                </button>
                <button className="btn btn-lg btn-glass" onClick={() => setCreating(true)}><FilePlus2 size={17} />新規案件</button>
                <Badge cls="badge-glass">{ai.enabled ? <><span className="live-dot" />AI 接続中・{ai.model}</> : 'AI 未接続（ルール抽出のみ）'}</Badge>
              </motion.div>
            </div>
          </div>
          <motion.div className="hero-seal" initial={{ scale: 2.4, rotate: -30, opacity: 0 }} animate={{ scale: 1, rotate: -12, opacity: 1 }}
            transition={{ delay: 0.9, type: 'spring', stiffness: 260, damping: 14 }}>
            <Hanko text="確" size={84} color="#f0cf7a" />
          </motion.div>
        </motion.section>

        <motion.div className="kpis" variants={stagger} initial="hidden" animate="show">
          {kpis.map((k) => (
            <motion.div key={k.label} className="card lift kpi" variants={fadeUp} style={{ '--kpi-glow': k.glow } as React.CSSProperties}>
              <div className="kpi-icon" style={{ background: k.bg }}><k.icon size={21} /></div>
              <div>
                <div className="kpi-label">{k.label}</div>
                <div className="kpi-value">{items ? <CountUp value={k.value} format={k.fmt} /> : '—'}</div>
                <div className="kpi-sub">{k.sub}</div>
              </div>
            </motion.div>
          ))}
        </motion.div>

        {inbox.length > 0 && (
          <motion.div className="card mt-24 inbox-card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
            <div className="card-head">
              <span className="inbox-ic"><Inbox size={16} /></span>
              <h3>{inbox[0].kind === 'requested' ? 'あなたの承認待ち' : '差し戻された案件'}</h3>
              <span className="inbox-n">{inbox.length}</span><span className="spacer" /><span className="small muted">{user}</span>
            </div>
            <motion.div variants={stagger} initial="hidden" animate="show">
              {inbox.map(({ p, kind }) => (
                <motion.div key={p.id} className={`inbox-row ${kind}`} variants={fadeUp} onClick={() => navigate(`/projects/${p.id}/output`)}>
                  <span className="inbox-kind">{kind === 'requested' ? <Clock size={14} /> : <Undo2 size={14} />}</span>
                  <div className="grow">
                    <div className="bold">{p.name}<span className="mono xs muted" style={{ marginLeft: 8 }}>{p.quote_no}</span></div>
                    <div className="small text-2">{kind === 'requested' ? `${p.approval!.by} さんが承認を依頼` : `${p.approval!.by} さんが差戻し`}・{dt(p.approval!.at)}
                      {p.approval!.comment && <>・「{p.approval!.comment}」</>}</div>
                  </div>
                  <span className="num bold">{p.sale_total != null ? yen(p.sale_total) : '—'}</span>
                  <button className="btn btn-sm btn-primary">{kind === 'requested' ? '確認して承認' : '修正して再依頼'}<ArrowRight size={13} /></button>
                </motion.div>
              ))}
            </motion.div>
          </motion.div>
        )}

        <motion.div className="card mt-24" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <div className="card-head"><h3>案件一覧</h3><span className="spacer" /><span className="small muted">{list.length} 件</span></div>
          {items === null ? (
            <div className="card-body col">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 44 }} />)}</div>
          ) : list.length === 0 ? (
            <Empty icon={<FolderOpen size={28} />} title="まだ案件がありません">
              <div>「デモ案件で体験する」を押すと、架空の制御盤仕様書（主仕様書・変更連絡書・スキャン図面）を AI が読み解く様子から体験できます。</div>
              <button className="btn btn-magic mt-16" onClick={createDemo} disabled={demoBusy}>
                {demoBusy ? <Spinner /> : <Sparkles size={16} />}デモ案件で体験する
              </button>
            </Empty>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>見積番号</th><th>案件名 / 顧客</th><th>状態</th><th>収容判定</th><th className="right">要確認</th>
                    <th className="right">見積金額（税抜）</th><th>提出期限</th><th>担当</th><th>更新</th><th />
                  </tr>
                </thead>
                <motion.tbody variants={stagger} initial="hidden" animate="show">
                  {list.map((p) => (
                    <motion.tr key={p.id} variants={fadeUp} className="clickable" onClick={() => navigate(`/projects/${p.id}/${p.stats ? 'review' : 'documents'}`)}>
                      <td className="mono nowrap">{p.quote_no}</td>
                      <td>
                        <div className="project-row-name">{p.name}</div>
                        <div className="small muted">{p.customer || '—'} ・ 資料 {p.documents} 件</div>
                      </td>
                      <td><Badge cls={PROJECT_STATUS[p.status] || 'badge-gray'}>{p.status}</Badge></td>
                      <td>{p.verdict ? <Badge cls={VERDICT[p.verdict].cls}>{VERDICT[p.verdict].label}</Badge> : <span className="muted">—</span>}</td>
                      <td className="right num">
                        {p.stats ? (p.stats.blocking > 0 ? <span style={{ color: 'var(--danger)', fontWeight: 800 }}>{p.stats.blocking}</span> : <span className="muted">0</span>) : '—'}
                      </td>
                      <td className="right num bold">{p.sale_total ? yen(p.sale_total) : '—'}</td>
                      <td className="nowrap">{dateOnly(p.due_date)}</td>
                      <td className="nowrap">{p.owner}</td>
                      <td className="small muted nowrap">{dt(p.updated_at)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <button className="btn btn-ghost btn-icon btn-sm" title="削除" aria-label={`${p.quote_no} を削除`} onClick={() => setConfirmDel(p)}><Trash2 size={15} /></button>
                      </td>
                    </motion.tr>
                  ))}
                </motion.tbody>
              </table>
            </div>
          )}
        </motion.div>

        <div className="mt-24 two-col" style={{ '--side': 'minmax(0, 0.67fr)', gap: 20, alignItems: 'stretch' } as React.CSSProperties}>
          <motion.div className="card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <div className="card-head"><h3>処理の流れ</h3><span className="small muted">各工程で担当者が確認・修正し、最終判断は人が行います</span></div>
            <motion.div className="card-body flow" variants={stagger} initial="hidden" animate="show">
              {FLOW.map((f, i) => (
                <motion.div key={f.title} className="flow-item" data-kanji={f.kanji} variants={fadeUp} whileHover={{ y: -4 }}>
                  <div className="fi-num" style={{ color: f.color }}>其の{['一', '二', '三', '四', '五'][i]}</div>
                  <div className="fi-title">{f.title}</div>
                  <div className="fi-desc">{f.desc}</div>
                </motion.div>
              ))}
            </motion.div>
          </motion.div>
          <motion.div className="card ai-card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
            <div className="card-head"><h3><span className="magic-text">AI</span>でできること</h3><span className="spacer" />
              <Badge cls={ai.enabled ? 'badge-ai' : 'badge-gray'}>{ai.enabled ? '利用可能' : '未接続'}</Badge></div>
            <motion.div className="card-body col gap-12" variants={stagger} initial="hidden" animate="show">
              {AI_FEATURES.map((f) => (
                <motion.div key={f.title} className="row gap-12" style={{ alignItems: 'flex-start' }} variants={fadeUp}>
                  <div className="ai-avatar"><f.icon size={16} /></div>
                  <div><div className="bold">{f.title}</div><div className="small text-2">{f.desc}</div></div>
                </motion.div>
              ))}
            </motion.div>
          </motion.div>
        </div>
      </div>

      {creating && <NewProjectDialog items={items ?? []} onClose={() => setCreating(false)} />}
      {confirmDel && (
        <Modal title="案件を削除しますか？" onClose={() => setConfirmDel(null)}
          footer={<><button className="btn" onClick={() => setConfirmDel(null)}>キャンセル</button>
            <button className="btn btn-danger" onClick={() => remove(confirmDel)}><Trash2 size={15} />削除する</button></>}>
          <div>{confirmDel.quote_no}「{confirmDel.name}」と登録資料・解析結果をすべて削除します。この操作は元に戻せません。</div>
        </Modal>
      )}
    </div>
  )
}
