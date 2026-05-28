import { useState, useEffect } from 'react'
import './App.css'
import Login from './pages/Login'
import { supabase } from './lib/supabase'

const API = 'https://portaliq-production.up.railway.app'

const TEAMS = [
  { name: 'Florida State Seminoles',   slug: 'Florida State Seminoles',   abbr: 'FSU', primary: '782f40', accent: 'ceb888' },
  { name: 'Alabama Crimson Tide',      slug: 'Alabama Crimson Tide',      abbr: 'ALA', primary: '9e1b32', accent: 'f1f2f3' },
  { name: 'Georgia Bulldogs',          slug: 'Georgia Bulldogs',          abbr: 'UGA', primary: 'ba0c2f', accent: 'd4af37' },
  { name: 'Ohio State Buckeyes',       slug: 'Ohio State Buckeyes',       abbr: 'OSU', primary: 'bb0000', accent: 'd4d4d4' },
  { name: 'Michigan Wolverines',       slug: 'Michigan Wolverines',       abbr: 'UM',  primary: '00274c', accent: 'ffcb05' },
  { name: 'Texas Longhorns',           slug: 'Texas Longhorns',           abbr: 'TEX', primary: 'bf5700', accent: 'ffffff' },
  { name: 'LSU Tigers',                slug: 'LSU Tigers',                abbr: 'LSU', primary: '461d7c', accent: 'fdd023' },
  { name: 'Clemson Tigers',            slug: 'Clemson Tigers',            abbr: 'CU',  primary: 'f56600', accent: '522d80' },
  { name: 'Notre Dame Fighting Irish', slug: 'Notre Dame Fighting Irish', abbr: 'ND',  primary: '0c2340', accent: 'c99700' },
  { name: 'Auburn Tigers',             slug: 'Auburn Tigers',             abbr: 'AUB', primary: '002b5c', accent: 'f26522' },
]

const RISK = {
  CRITICAL: { color: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
  HIGH:     { color: '#f97316', bg: 'rgba(249,115,22,0.15)' },
  MEDIUM:   { color: '#eab308', bg: 'rgba(234,179,8,0.15)'  },
  LOW:      { color: '#22c55e', bg: 'rgba(34,197,94,0.15)'  },
}

const BREAKDOWN_LABELS = {
  portal_attractiveness: 'Portal Attractiveness',
  nil_market_gap:        'NIL Market Gap',
  depth_pressure:        'Depth Pressure',
  depth_rank_risk:       'Depth Rank Risk',
  eligibility_risk:      'Eligibility Risk',
}

function normalizeGroup(g) {
  if (!g || g === 'DB') return 'Defense'
  return g
}

function fmtNIL(n) {
  if (!n) return '—'
  if (n >= 1000000) return `$${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `$${Math.round(n / 1000)}K`
  return `$${n}`
}

function RiskBadge({ label }) {
  const r = RISK[label] || RISK.LOW
  return (
    <span style={{
      background: r.bg, color: r.color,
      border: `1px solid ${r.color}40`,
      padding: '2px 8px', borderRadius: 4,
      fontSize: 10, fontFamily: 'monospace',
      letterSpacing: 1, fontWeight: 700,
    }}>{label}</span>
  )
}

function VolatilityBar({ score, breakdown }) {
  const [hovered, setHovered] = useState(false)
  const color = score >= 70 ? '#ef4444' : score >= 50 ? '#f97316' : score >= 30 ? '#eab308' : '#22c55e'

  return (
    <div style={{ position: 'relative' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'help' }}>
        <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2 }}>
          <div style={{ width: `${score}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.6s ease' }} />
        </div>
        <span style={{ fontSize: 12, fontFamily: 'monospace', color, minWidth: 32, textAlign: 'right', fontWeight: 700 }}>{score}</span>
      </div>

      {hovered && breakdown && (
        <div style={{
          position: 'absolute', bottom: 'calc(100% + 10px)', right: 0,
          background: '#0a0e1a', border: '1px solid rgba(255,255,255,0.14)',
          borderRadius: 8, padding: '12px 16px', zIndex: 999,
          minWidth: 240, boxShadow: '0 12px 40px rgba(0,0,0,0.7)',
          pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 10, color: '#6b7a99', letterSpacing: 2, marginBottom: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>
            Why this score?
          </div>
          {Object.entries(breakdown).map(([key, val]) => (
            <div key={key} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 12, color: '#c8ccd6' }}>{BREAKDOWN_LABELS[key] || key}</span>
                <span style={{ fontSize: 12, fontFamily: 'monospace', color, fontWeight: 700 }}>{val}</span>
              </div>
              <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2 }}>
                <div style={{ width: `${val}%`, height: '100%', background: color, borderRadius: 2, opacity: 0.6 }} />
              </div>
            </div>
          ))}
          <div style={{
            position: 'absolute', bottom: -5, right: 44,
            width: 8, height: 8, background: '#0a0e1a',
            borderRight: '1px solid rgba(255,255,255,0.14)',
            borderBottom: '1px solid rgba(255,255,255,0.14)',
            transform: 'rotate(45deg)',
          }} />
        </div>
      )}
    </div>
  )
}

// ── Volatility Tab ────────────────────────────────────────────
function VolatilityView({ team, primary, accent }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter]   = useState('ALL')

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetch(`${API}/rosters/${encodeURIComponent(team)}/volatility`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [team])

  if (loading) return <div className="loading">Loading volatility model...</div>
  if (!data || data.error) return <div className="loading">No data found for {team}</div>

  const players = filter === 'ALL'
    ? data.players
    : data.players.filter(p => p.risk_label === filter)

  const tvi = data.team_volatility_index
  const tviColor = tvi >= 70 ? '#ef4444' : tvi >= 50 ? '#f97316' : tvi >= 30 ? '#eab308' : '#22c55e'

  // Normalize position groups — collapse DB into Defense
  const posVol = {}
  Object.entries(data.position_volatility || {}).forEach(([group, info]) => {
    const key = normalizeGroup(group)
    if (!posVol[key]) {
      posVol[key] = { ...info }
    } else {
      const total = posVol[key].player_count + info.player_count
      const avg = Math.round(
        ((posVol[key].avg_volatility * posVol[key].player_count) +
         (info.avg_volatility * info.player_count)) / total * 10) / 10
      posVol[key].avg_volatility = avg
      posVol[key].max_volatility = Math.max(posVol[key].max_volatility, info.max_volatility)
      posVol[key].player_count   = total
      posVol[key].risk_label     = avg >= 70 ? 'CRITICAL' : avg >= 50 ? 'HIGH' : avg >= 30 ? 'MEDIUM' : 'LOW'
    }
  })

  return (
    <div className="view-container">
      <div className="tvi-hero" style={{ borderLeftColor: `#${primary}` }}>
        <div className="tvi-left">
          <div className="tvi-label">Team Volatility Index</div>
          <div className="tvi-score" style={{ color: tviColor }}>{tvi}</div>
          <div className="tvi-sub">2026 Season · {data.players.length} players</div>
        </div>
        <div className="tvi-right">
          <div className="risk-pills">
            {Object.entries(data.risk_summary).map(([label, count]) => (
              <div key={label} className="risk-pill" style={{ borderColor: RISK[label.toUpperCase()]?.color }}>
                <span style={{ color: RISK[label.toUpperCase()]?.color, fontWeight: 700 }}>{count}</span>
                <span className="risk-pill-label">{label.toUpperCase()}</span>
              </div>
            ))}
          </div>
          <div className="retention-cost">
            <span className="ret-label">Est. Retention Cost</span>
            <span className="ret-value" style={{ color: `#${accent}` }}>{fmtNIL(data.estimated_retention_cost)}</span>
          </div>
        </div>
      </div>

      <div className="pos-group-grid">
        {Object.entries(posVol).map(([group, info]) => (
          <div key={group} className="pos-group-card" style={{ borderColor: (RISK[info.risk_label]?.color || '#888') + '60' }}>
            <div className="pos-group-name">{group}</div>
            <div className="pos-group-score" style={{ color: RISK[info.risk_label]?.color }}>{info.avg_volatility}</div>
            <RiskBadge label={info.risk_label} />
            <div className="pos-group-count">{info.player_count} players</div>
          </div>
        ))}
      </div>

      <div className="filter-bar">
        {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(f => (
          <button
            key={f}
            className={`filter-btn ${filter === f ? 'active' : ''}`}
            style={filter === f ? { borderColor: `#${accent}`, color: `#${accent}` } : {}}
            onClick={() => setFilter(f)}
          >{f}</button>
        ))}
        <span className="filter-count">{players.length} players</span>
      </div>

      <div className="player-list">
        {players.map((p, i) => (
          <div key={i} className="player-row">
            <div className="player-headshot-wrap">
              {p.headshot
                ? <img src={p.headshot} className="player-headshot" alt={p.player_name}
                    onError={e => { e.target.style.display = 'none' }} />
                : <div className="player-headshot-placeholder">{p.jersey || '?'}</div>
              }
            </div>
            <div className="player-info">
              <div className="player-name">{p.short_name || p.player_name}</div>
              <div className="player-meta">
                <span className="player-pos">{p.position}</span>
                <span className="player-class-badge">{p.class_abbreviation}</span>
                <span className="player-depth">#{p.depth_rank} depth</span>
              </div>
            </div>
            <div className="player-nil">{fmtNIL(p.est_player_nil_cost)}</div>
            <div className="player-vol-wrap">
              <VolatilityBar score={p.volatility_score} breakdown={p.breakdown} />
              <RiskBadge label={p.risk_label} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Depth Chart Tab ───────────────────────────────────────────
function DepthChartView({ team, primary, accent }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [side, setSide]       = useState('Offense')

  useEffect(() => {
    setLoading(true)
    setData(null)
    fetch(`${API}/rosters/${encodeURIComponent(team)}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [team])

  if (loading) return <div className="loading">Loading roster...</div>
  if (!data || data.error) return <div className="loading">No roster found for {team}</div>

  // Normalize groups — collapse DB into Defense
  const rawGroups = data.roster || {}
  const groups = {}
  Object.entries(rawGroups).forEach(([group, positions]) => {
    const key = normalizeGroup(group)
    if (!groups[key]) groups[key] = {}
    Object.entries(positions).forEach(([pos, players]) => {
      if (!groups[key][pos]) groups[key][pos] = []
      groups[key][pos].push(...players)
    })
  })

  const sides        = Object.keys(groups)
  const activeSide   = groups[side] ? side : sides[0]
  const currentGroup = groups[activeSide] || {}
  const classBreak   = data.class_breakdown || {}

  return (
    <div className="view-container">
      <div className="roster-summary">
        <div className="roster-stat">
          <span className="rs-value">{data.total_players}</span>
          <span className="rs-label">Total Players</span>
        </div>
        {Object.entries(classBreak).map(([cls, count]) => (
          <div key={cls} className="roster-stat">
            <span className="rs-value">{count}</span>
            <span className="rs-label">{cls}</span>
          </div>
        ))}
      </div>

      <div className="side-tabs">
        {sides.map(s => (
          <button
            key={s}
            className={`side-tab ${activeSide === s ? 'active' : ''}`}
            style={activeSide === s ? { borderBottomColor: `#${accent}`, color: `#${accent}` } : {}}
            onClick={() => setSide(s)}
          >{s}</button>
        ))}
      </div>

      {Object.entries(currentGroup).map(([pos, players]) => (
        <div key={pos} className="position-group">
          <div className="pos-header">
            <span className="pos-title" style={{ color: `#${accent}` }}>{pos}</span>
            <span className="pos-count">{players.length}</span>
          </div>
          {players.map((p, i) => (
            <div key={i} className="depth-row">
              <div className="depth-num" style={{ color: i === 0 ? `#${accent}` : 'rgba(255,255,255,0.3)' }}>
                {i + 1}
              </div>
              <div className="depth-headshot-wrap">
                {p.headshot
                  ? <img src={p.headshot} className="depth-headshot" alt={p.player_name}
                      onError={e => { e.target.style.display = 'none' }} />
                  : <div className="depth-headshot-ph">#{p.jersey}</div>
                }
              </div>
              <div className="depth-info">
                <div className="depth-name">{p.short_name || p.player_name}</div>
                <div className="depth-meta">
                  <span>#{p.jersey}</span>
                  <span className="dot">·</span>
                  <span>{p.class_abbreviation}</span>
                  <span className="dot">·</span>
                  <span>{p.height}</span>
                  <span className="dot">·</span>
                  <span>{p.weight} lbs</span>
                </div>
              </div>
              <div className="depth-nil">{fmtNIL(p.est_player_nil_cost)}</div>
              <div className="depth-nil-bar">
                <div style={{
                  width: `${Math.min((p.transfer_value_score / 1.5) * 100, 100)}%`,
                  height: 3, background: `#${accent}`,
                  borderRadius: 2, opacity: 0.7,
                }} />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────
export default function App() {
  const [team, setTeam]         = useState(TEAMS[0])
  const [tab, setTab]           = useState('volatility')
  const [teamOpen, setTeamOpen] = useState(false)
  const [user, setUser]         = useState(null)
  const [authLoading, setAuthLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      setAuthLoading(false)
    })
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null)
    })
    return () => subscription.unsubscribe()
  }, [])

  if (authLoading) return <div className="loading" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Loading...</div>
  if (!user) return <Login onLogin={setUser} />

  const primary = team.primary
  const accent  = team.accent

  const handleLogout = async () => {
    await supabase.auth.signOut()
    setUser(null)
  }

  return (
    <div className="app" style={{ '--primary': `#${primary}`, '--accent': `#${accent}` }}>
      <nav className="navbar">
        <div className="nav-brand">
          <span className="nav-logo">RE</span>
          <span className="nav-title">ROSTER<span style={{ color: `#${accent}` }}>EDGE</span></span>
        </div>

        <div className="team-selector">
          <button className="team-btn" onClick={() => setTeamOpen(!teamOpen)}>
            <span className="team-abbr" style={{ background: `#${primary}`, color: `#${accent}` }}>{team.abbr}</span>
            <span className="team-name">{team.name}</span>
            <span className="chevron">{teamOpen ? '▲' : '▼'}</span>
          </button>
          {teamOpen && (
            <div className="team-dropdown">
              {TEAMS.map(t => (
                <button
                  key={t.slug}
                  className={`team-option ${t.slug === team.slug ? 'selected' : ''}`}
                  style={t.slug === team.slug ? { background: `#${t.primary}20`, color: `#${t.accent}` } : {}}
                  onClick={() => { setTeam(t); setTeamOpen(false) }}
                >
                  <span className="opt-abbr" style={{ background: `#${t.primary}`, color: `#${t.accent}` }}>{t.abbr}</span>
                  {t.name}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="nav-badge">2026</div>
        <button
          onClick={handleLogout}
          style={{
            background: 'transparent', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 6, color: '#8892a8', padding: '5px 12px',
            fontSize: 11, letterSpacing: 1, textTransform: 'uppercase',
            cursor: 'pointer', fontFamily: 'DM Sans, sans-serif',
          }}
        >Sign Out</button>
      </nav>

      <div className="tab-bar">
        {[
          { id: 'volatility', label: 'Volatility'  },
          { id: 'depth',      label: 'Depth Chart' },
        ].map(t => (
          <button
            key={t.id}
            className={`tab-btn ${tab === t.id ? 'active' : ''}`}
            style={tab === t.id ? { color: `#${accent}`, borderBottomColor: `#${accent}` } : {}}
            onClick={() => setTab(t.id)}
          >{t.label}</button>
        ))}
      </div>

      <main className="main">
        {tab === 'volatility' && <VolatilityView team={team.slug} primary={primary} accent={accent} />}
        {tab === 'depth'      && <DepthChartView  team={team.slug} primary={primary} accent={accent} />}
      </main>
    </div>
  )
}