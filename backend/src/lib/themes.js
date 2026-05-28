export const TEAMS = {
  'florida-state': {
    id: 'florida-state',
    abbr: 'FSU',
    name: 'Florida State Seminoles',
    apiName: 'Florida State',
    primary: '#782F40',
    accent: '#CEB888',
    dark: '#5a232f',
  },
  'michigan': {
    id: 'michigan',
    abbr: 'UM',
    name: 'Michigan Wolverines',
    apiName: 'Michigan',
    primary: '#00274C',
    accent: '#FFCB05',
    dark: '#001a35',
  },
  'ohio-state': {
    id: 'ohio-state',
    abbr: 'OSU',
    name: 'Ohio State Buckeyes',
    apiName: 'Ohio State',
    primary: '#BB0000',
    accent: '#d4d4d4',
    dark: '#8B0000',
  },
  'alabama': {
    id: 'alabama',
    abbr: 'ALA',
    name: 'Alabama Crimson Tide',
    apiName: 'Alabama',
    primary: '#9E1B32',
    accent: '#F1F2F3',
    dark: '#7a1426',
  },
  'georgia': {
    id: 'georgia',
    abbr: 'UGA',
    name: 'Georgia Bulldogs',
    apiName: 'Georgia',
    primary: '#BA0C2F',
    accent: '#d4af37',
    dark: '#8a0922',
  },
}

export function applyTheme(team) {
  const root = document.documentElement
  root.style.setProperty('--team-primary', team.primary)
  root.style.setProperty('--team-accent', team.accent)
  root.style.setProperty('--team-dark', team.dark)
}