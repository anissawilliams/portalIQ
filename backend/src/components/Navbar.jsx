import React from 'react'
import { TEAMS, applyTheme } from '../lib/themes'

export default function Navbar({ currentTeam, setCurrentTeam }) {
  const handleTeamChange = (teamId) => {
    const team = TEAMS[teamId]
    applyTheme(team)
    setCurrentTeam(team)
  }

  return (
    <nav style={{
      background: '#0d1220',
      borderBottom: '1px solid #1e2740',
      padding: '10px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 100,
    }}>
      <div style={{
        fontFamily: 'Barlow Condensed, sans-serif',
        fontSize: '22px',
        fontWeight: 700,
        color: 'var(--team-accent)',
        letterSpacing: '1px',
        transition: 'color 0.3s',
      }}>
        ROSTER<span style={{ color: '#e8eaf0' }}>EDGE</span>
      </div>

      <div style={{ display: 'flex', gap: '6px' }}>
        {Object.values(TEAMS).map(team => (
          <button
            key={team.id}
            onClick={() => handleTeamChange(team.id)}
            style={{
              background: currentTeam?.id === team.id ? 'rgba(255,255,255,0.04)' : '#131829',
              border: currentTeam?.id === team.id
                ? '1px solid var(--team-accent)'
                : '1px solid #1e2740',
              borderRadius: '6px',
              padding: '4px 10px',
              fontSize: '11px',
              fontWeight: 600,
              color: currentTeam?.id === team.id ? 'var(--team-accent)' : '#8892a8',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'all 0.2s',
              fontFamily: 'DM Sans, sans-serif',
            }}
          >
            <span style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: team.primary,
              border: `1px solid ${team.accent}`,
              flexShrink: 0,
            }} />
            {team.abbr}
          </button>
        ))}
      </div>
    </nav>
  )
}