import React, { useState } from 'react'
import { supabase } from '../lib/supabase'

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    setLoading(true)
    setError(null)
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) {
      setError(error.message)
      setLoading(false)
    } else {
      onLogin(data.user)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', background: '#0a0e1a',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#0d1220', border: '1px solid #1e2740',
        borderRadius: '16px', padding: '48px 40px',
        width: '100%', maxWidth: '400px',
      }}>
        <div style={{
          fontFamily: 'Barlow Condensed, sans-serif',
          fontSize: '28px', fontWeight: 700,
          color: '#CEB888', letterSpacing: '1px',
          marginBottom: '4px', textAlign: 'center',
        }}>
          ROSTER<span style={{ color: '#e8eaf0' }}>EDGE</span>
        </div>
        <div style={{
          fontSize: '12px', color: '#8892a8',
          textAlign: 'center', marginBottom: '32px',
          letterSpacing: '1px', textTransform: 'uppercase',
        }}>
          Roster Intelligence Platform
        </div>

        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '11px', color: '#8892a8', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '1px' }}>
            Email
          </div>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@school.edu"
            style={{
              width: '100%', padding: '10px 14px',
              background: '#131829', border: '1px solid #1e2740',
              borderRadius: '8px', color: '#e8eaf0',
              fontSize: '14px', outline: 'none',
              fontFamily: 'DM Sans, sans-serif',
            }}
          />
        </div>

        <div style={{ marginBottom: '24px' }}>
          <div style={{ fontSize: '11px', color: '#8892a8', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '1px' }}>
            Password
          </div>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            placeholder="••••••••"
            style={{
              width: '100%', padding: '10px 14px',
              background: '#131829', border: '1px solid #1e2740',
              borderRadius: '8px', color: '#e8eaf0',
              fontSize: '14px', outline: 'none',
              fontFamily: 'DM Sans, sans-serif',
            }}
          />
        </div>

        {error && (
          <div style={{
            background: '#3d1515', border: '1px solid #7a2a2a',
            borderRadius: '8px', padding: '10px 14px',
            color: '#f87171', fontSize: '13px', marginBottom: '16px',
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleLogin}
          disabled={loading}
          style={{
            width: '100%', padding: '12px',
            background: '#782F40', border: 'none',
            borderRadius: '8px', color: '#CEB888',
            fontSize: '14px', fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
            fontFamily: 'Barlow Condensed, sans-serif',
            letterSpacing: '1px', textTransform: 'uppercase',
            opacity: loading ? 0.7 : 1,
            transition: 'opacity 0.2s',
          }}
        >
          {loading ? 'Signing In...' : 'Sign In'}
        </button>
      </div>
    </div>
  )
}