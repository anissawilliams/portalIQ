import React, { useState, useEffect } from 'react'
import { getRoster } from '../lib/api'

const RISK_STYLES = {
  low:  { background: '#0d2d1e', color: '#4caf82', border: '1px solid #1a5a3a', label: 'Low' },
  med:  { background: '#2d2010', color: '#f0a040', border: '1px solid #7a5020', label: 'Med' },
  high: { background: '#3d1515', color: '#f87171', border: '1px solid #7a2a2a', label: 'High' },
}

function getRisk(score) {
  if (score >= 0.7) return 'low'
  if (score >= 0.5) return 'med'
  return 'high'
}

function formatNIL(val) {
  if (!val) return 'N/A'
  if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`
  if (val >= 1000) return `$${Math.round(val / 1000)}K`
  return `$${Math.round(val)}`
}

function formatScore(val) {
  return Math.round((val || 0) * 60)
}

function Tag({ style }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '2px 8px', borderRadius: '4px',
      fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px',
      ...style,
    }}>
      {style.label}
    </span>
  )
}

function PlayerRow({ player }) {
  const risk = getRisk(player.transfer_value_score)
  const riskStyle = RISK_STYLES[risk]
  const isHighNIL = player.est_player_nil_cost >= 75000
  const score = formatScore(player.transfer_value_score)
  const borderColor = risk === 'high' ? '#e05555'
    : player.is_upgrade ? 'var(--team-accent)' : '#8b5cf6'

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '44px 34px 1fr 80px 110px 90px 70px',
        alignItems: 'center', gap: '10px',
        padding: '8px 12px', borderRadius: '6px',
        background: '#0d1220', border: '1px solid #1e2740',
        borderLeft: `3px solid ${borderColor}`,
        marginBottom: '3px', cursor: 'pointer', transition: 'background 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.background = '#131829'}
      onMouseLeave={e => e.currentTarget.style.background = '#0d1220'}
    >
      <div style={{ fontFamily: 'Barlow Condensed, sans-serif', fontSize: '13px', color: '#8892a8', textAlign: 'center' }}>
        #{player.depth_rank}
      </div>
      <div style={{
        background: '#1a2340', borderRadius: '4px', padding: '2px 5px',
        fontSize: '10px', fontWeight: 600, color: '#8892a8',
        textAlign: 'center', fontFamily: 'Barlow Condensed, sans-serif',
      }}>
        {player.position}
      </div>
      <div>
        <div style={{ fontSize: '13px', fontWeight: 500, color: '#e8eaf0' }}>{player.player_name}</div>
        <div style={{ fontSize: '10px', color: '#8892a8', marginTop: '1px' }}>
          {player.origin_school} · {player.stars}★ · {player.eligibility}
        </div>
      </div>
      <div style={{
        fontFamily: 'Barlow Condensed, sans-serif', fontSize: '13px', fontWeight: 600,
        color: isHighNIL ? 'var(--team-accent)' : '#4caf82',
        textAlign: 'right', transition: 'color 0.3s',
      }}>
        {formatNIL(player.est_player_nil_cost)}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <div style={{ flex: 1, height: '4px', background: '#1e2740', borderRadius: '2px', overflow: 'hidden' }}>
          <div style={{
            width: `${Math.min(score, 100)}%`, height: '100%', borderRadius: '2px',
            background: 'var(--team-accent)', transition: 'background 0.3s',
          }} />
        </div>
        <div style={{ fontSize: '11px', color: '#8892a8', minWidth: '24px', textAlign: 'right', fontFamily: 'Barlow Condensed, sans-serif' }}>
          {score}
        </div>
      </div>
      <div style={{
        background: player.is_upgrade ? '#0d2d1e' : '#2d1f5e',
        color: player.is_upgrade ? '#4caf82' : '#a78bfa',
        border: player.is_upgrade ? '1px solid #1a5a3a' : '1px solid #4c3a9e',
        display: 'inline-flex', alignItems: 'center',
        padding: '2px 8px', borderRadius: '4px',
        fontSize: '10px', fontWeight: 600,
      }}>
        {player.is_upgrade ? 'Upgrade' : 'Lateral'}
      </div>
      <Tag style={riskStyle} />
    </div>
  )
}

function PositionGroup({ position, players, side }) {
  return (
    <div style={{ marginBottom: '14px' }}>
      <div style={{
        fontFamily: 'Barlow Condensed, sans-serif',
        fontSize: '11px', fontWeight: 600,
        letterSpacing: '2px', textTransform: 'uppercase',
        marginBottom: '6px', paddingLeft: '8px',
        borderLeft: `2px solid ${side === 'Offense' ? 'var(--team-accent)' : '#4c8af0'}`,
        color: side === 'Offense' ? 'var(--team-accent)' : '#4c8af0',
        transition: 'color 0.3s, border-color 0.3s',
      }}>
        {position}
      </div>
      {players.map((p, i) => <PlayerRow key={i} player={p} />)}
    </div>
  )
}

export default function DepthChart({ team }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('Offense')

  useEffect(() => {
    setLoading(true)
    setError(null)
      getRoster(team.apiName)
        .then(d => {
          console.log('roster response:', d)
          setData(d);
          setLoading(false)
        })
  }, [team])


  if (loading) return (
    <div style={{ padding: '40px', textAlign: 'center', color: '#8892a8', fontFamily: 'Barlow Condensed, sans-serif', fontSize: '18px', letterSpacing: '2px' }}>
      LOADING ROSTER...
    </div>
  )

  if (error) return (
    <div style={{ padding: '40px', textAlign: 'center', color: '#e05555' }}>
      Error: {error}
    </div>
  )
    console.log('team:', team)
        console.log('data:', data)
        console.log('loading:', loading)
        console.log('error:', error)

  const rosterGroups = data?.roster || {}
  const flat = data?.flat || []
  const totalNIL = flat.reduce((sum, p) => sum + (p.est_player_nil_cost || 0), 0)
  const portalCount = flat.length
  const highRisk = flat.filter(p => getRisk(p.transfer_value_score) === 'high').length
  const avgScore = flat.length ? Math.round(flat.reduce((s, p) => s + formatScore(p.transfer_value_score), 0) / flat.length) : 0

  const tabs = Object.keys(rosterGroups)

  return (
    <div style={{ padding: '20px', maxWidth: '1100px', margin: '0 auto' }}>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '20px' }}>
        {[
          { label: 'Portal Class NIL', value: formatNIL(totalNIL), color: 'var(--team-accent)' },
          { label: 'Portal Additions', value: portalCount, color: '#e8eaf0' },
          { label: 'High Risk', value: highRisk, color: '#e05555' },
          { label: 'Avg Moneyball', value: avgScore, color: '#4caf82' },
        ].map(stat => (
          <div key={stat.label} style={{
            background: '#0d1220', border: '1px solid #1e2740',
            borderTop: '2px solid var(--team-primary)',
            borderRadius: '8px', padding: '12px 14px',
            transition: 'border-color 0.3s',
          }}>
            <div style={{ fontSize: '10px', color: '#8892a8', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>
              {stat.label}
            </div>
            <div style={{ fontFamily: 'Barlow Condensed, sans-serif', fontSize: '22px', fontWeight: 700, color: stat.color, transition: 'color 0.3s' }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '2px', marginBottom: '16px', borderBottom: '1px solid #1e2740' }}>
        {tabs.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            padding: '8px 20px', fontSize: '12px', fontWeight: 500,
            color: activeTab === tab ? 'var(--team-accent)' : '#8892a8',
            borderBottom: activeTab === tab ? '2px solid var(--team-accent)' : '2px solid transparent',
            background: 'none', border: 'none',
            cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '1px',
            transition: 'all 0.2s', fontFamily: 'DM Sans, sans-serif',
          }}>
            {tab}
          </button>
        ))}
      </div>

      {/* Column Headers */}
      <div style={{ display: 'grid', gridTemplateColumns: '44px 34px 1fr 80px 110px 90px 70px', gap: '10px', padding: '4px 12px', marginBottom: '8px' }}>
        {['Depth', 'Pos', 'Player', 'NIL', 'Moneyball', 'Status', 'Risk'].map((h, i) => (
          <div key={h} style={{ fontSize: '9px', color: '#6b7a99', textTransform: 'uppercase', letterSpacing: '1px', textAlign: i > 2 ? 'right' : 'left' }}>
            {h}
          </div>
        ))}
      </div>

      {/* Position Groups */}
      {rosterGroups[activeTab] && Object.entries(rosterGroups[activeTab]).map(([pos, players]) => (
        <PositionGroup key={pos} position={pos} players={players} side={activeTab} />
      ))}

    </div>
  )
}