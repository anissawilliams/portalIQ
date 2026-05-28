const BASE_URL = 'https://portaliq-production.up.railway.app'

export async function getRoster(team, season = null) {
  const query = new URLSearchParams({ sport: 'football' })
  if (season) query.set('season', season)
  const res = await fetch(`${BASE_URL}/players/roster/${encodeURIComponent(team)}?${query}`)
  if (!res.ok) throw new Error('Failed to fetch roster')
  return res.json()
}

export async function getPlayers(team, params = {}) {
  const query = new URLSearchParams({ sport: 'football', ...params })
  const res = await fetch(`${BASE_URL}/players/search?${query}`)
  if (!res.ok) throw new Error('Failed to fetch players')
  return res.json()
}

export async function getTeamProfile(team) {
  const res = await fetch(`${BASE_URL}/teams/${encodeURIComponent(team)}?sport=football`)
  if (!res.ok) throw new Error('Failed to fetch team')
  return res.json()
}

export async function getRetentionRisk(team) {
  const res = await fetch(`${BASE_URL}/projections/retention-risk/${encodeURIComponent(team)}?sport=football`)
  if (!res.ok) throw new Error('Failed to fetch retention risk')
  return res.json()
}

export async function getClassProjection(team) {
  const res = await fetch(`${BASE_URL}/projections/class/${encodeURIComponent(team)}?sport=football`)
  if (!res.ok) throw new Error('Failed to fetch class projection')
  return res.json()
}