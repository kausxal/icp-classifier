import { useState, useEffect, createContext, useContext } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import axios from 'axios'

const API_BASE = ''

const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const savedUser = localStorage.getItem('icp_user')
    if (savedUser) {
      setUser(JSON.parse(savedUser))
    }
    setLoading(false)
  }, [])

  const login = async (username, password) => {
    try {
      const res = await axios.post(`${API_BASE}/admin/login`, 
        new URLSearchParams({ username, password }),
        { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
      )
      const userData = { username }
      setUser(userData)
      localStorage.setItem('icp_user', JSON.stringify(userData))
      return { success: true }
    } catch (err) {
      return { success: false, error: 'Invalid credentials' }
    }
  }

  const logout = () => {
    setUser(null)
    localStorage.removeItem('icp_user')
  }

  if (loading) {
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={!user ? <Login /> : <Navigate to="/dashboard" />} />
          <Route path="/*" element={user ? <Layout /> : <Navigate to="/login" />} />
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  )
}

function Login() {
  const { login } = useAuth()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    const username = e.target.username.value
    const password = e.target.password.value
    const result = await login(username, password)
    setLoading(false)
    if (!result.success) {
      setError(result.error)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-600 to-indigo-700 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md">
        <h1 className="text-3xl font-bold text-center mb-8 text-gray-800">ICP Classifier</h1>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-gray-700 text-sm font-bold mb-2">Username</label>
            <input type="text" name="username" required className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500" />
          </div>
          <div>
            <label className="block text-gray-700 text-sm font-bold mb-2">Password</label>
            <input type="password" name="password" required className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500" />
          </div>
          {error && <div className="p-3 bg-red-100 text-red-700 rounded-lg text-center">{error}</div>}
          <button type="submit" disabled={loading} className="w-full bg-purple-600 text-white py-3 rounded-lg font-bold hover:bg-purple-700 transition disabled:opacity-50">
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>
      </div>
    </div>
  )
}

function Layout() {
  const { logout, user } = useAuth()
  const location = useLocation()

  const navItems = [
    { path: '/dashboard', icon: 'chart-pie', label: 'Dashboard' },
    { path: '/leads', icon: 'users', label: 'Leads' },
    { path: '/clients', icon: 'building', label: 'Clients' },
    { path: '/integrations', icon: 'plug', label: 'Integrations' },
    { path: '/logs', icon: 'history', label: 'Activity Logs' },
    { path: '/settings', icon: 'settings', label: 'Settings' },
  ]

  const getIcon = (name) => {
    const icons = {
      'chart-pie': '📊', 'users': '👥', 'building': '🏢', 
      'plug': '🔌', 'history': '📜', 'settings': '⚙️'
    }
    return icons[name] || '•'
  }

  return (
    <div className="flex h-screen">
      <div className="w-64 bg-gray-900 text-white p-5 flex flex-col">
        <h1 className="text-2xl font-bold mb-8">🔬 ICP Classifier</h1>
        <div className="mb-6 pb-4 border-b border-gray-700">
          <div className="text-sm text-gray-400">Logged in as</div>
          <div className="font-bold">{user?.username}</div>
        </div>
        <nav className="flex-1 space-y-2">
          {navItems.map(item => (
            <a key={item.path} href={item.path} className={`sidebar-link ${location.pathname === item.path ? 'active' : ''}`}>
              <span className="mr-2">{getIcon(item.icon)}</span>
              {item.label}
            </a>
          ))}
        </nav>
        <button onClick={logout} className="mt-auto py-2 px-4 rounded text-red-400 hover:bg-gray-800 text-left">
          🚪 Logout
        </button>
      </div>
      <div className="flex-1 overflow-auto p-8">
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/clients" element={<Clients />} />
          <Route path="/integrations" element={<Integrations />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </div>
    </div>
  )
}

function Dashboard() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/stats`)
      setStats(res.data)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }

  if (loading) return <div>Loading...</div>

  const cards = [
    { label: 'Total Leads', value: stats?.total_leads || 0, sub: `${stats?.last_7_days || 0} this week`, color: 'blue' },
    { label: 'Tier 1 (Hot)', value: stats?.tier1 || 0, color: 'green' },
    { label: 'Tier 2 (Warm)', value: stats?.tier2 || 0, color: 'yellow' },
    { label: 'CRM Pushed', value: (stats?.hubspot_pushed || 0) + (stats?.salesforce_pushed || 0), color: 'purple' },
  ]

  const colorMap = { blue: 'text-blue-600', green: 'text-green-600', yellow: 'text-yellow-600', purple: 'text-purple-600' }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        {cards.map((card, i) => (
          <div key={i} className="bg-white p-6 rounded-lg shadow">
            <div className="text-gray-500 text-sm">{card.label}</div>
            <div className={`text-3xl font-bold ${colorMap[card.color]}`}>{card.value}</div>
            {card.sub && <div className="text-green-500 text-sm mt-2">{card.sub}</div>}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-bold mb-4">Tier Distribution</h3>
          {stats?.tier_dist?.map((t, i) => {
            const pct = stats.total_leads > 0 ? (t.count / stats.total_leads * 100).toFixed(1) : 0
            return (
              <div key={i} className="mb-3">
                <div className="flex justify-between text-sm"><span>{t.tier}</span><span>{t.count} ({pct}%)</span></div>
                <div className="w-full bg-gray-200 rounded-full h-2 mt-1"><div className="bg-purple-600 h-2 rounded-full" style={{width: `${pct}%`}}></div></div>
              </div>
            )
          })}
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-bold mb-4">Top Clients</h3>
          {stats?.top_clients?.map((c, i) => (
            <div key={i} className="flex justify-between p-2 bg-gray-50 rounded mb-2">
              <span>{c.client_id}</span><span className="font-bold">{c.count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Leads() {
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState('')

  useEffect(() => {
    fetchLeads()
  }, [search, tier])

  const fetchLeads = async () => {
    try {
      const params = new URLSearchParams()
      if (search) params.append('search', search)
      if (tier) params.append('tier', tier)
      const res = await axios.get(`${API_BASE}/admin/leads?${params}`)
      setLeads(res.data)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }

  const getTierClass = (t) => {
    if (t === 'Tier 1') return 'bg-green-100 text-green-800'
    if (t === 'Tier 2') return 'bg-yellow-100 text-yellow-800'
    return 'bg-gray-100 text-gray-800'
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Leads</h1>
      <div className="mb-4 flex gap-4">
        <input type="text" placeholder="Search..." value={search} onChange={(e) => setSearch(e.target.value)} className="px-4 py-2 border rounded-lg w-64" />
        <select value={tier} onChange={(e) => setTier(e.target.value)} className="px-4 py-2 border rounded-lg">
          <option value="">All Tiers</option>
          <option value="Tier 1">Tier 1</option>
          <option value="Tier 2">Tier 2</option>
          <option value="Not ICP">Not ICP</option>
        </select>
      </div>
      <div className="bg-white rounded-lg shadow overflow-x">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left">Company</th>
              <th className="px-4 py-3 text-left">Contact</th>
              <th className="px-4 py-3 text-left">Tier</th>
              <th className="px-4 py-3 text-left">Score</th>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">CRM</th>
            </tr>
          </thead>
          <tbody>
            {leads.map(lead => (
              <tr key={lead.id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-3">{lead.company}</td>
                <td className="px-4 py-3">{lead.first_name} {lead.last_name}<br/><span className="text-gray-500 text-sm">{lead.email}</span></td>
                <td className="px-4 py-3"><span className={`px-2 py-1 rounded text-sm ${getTierClass(lead.tier)}`}>{lead.tier}</span></td>
                <td className="px-4 py-3">{lead.score}</td>
                <td className="px-4 py-3">{lead.recommended_action || '-'}</td>
                <td className="px-4 py-3">
                  {lead.pushed_to_hubspot && <span className="text-orange-500 mr-1">🔶</span>}
                  {lead.pushed_to_salesforce && <span className="text-blue-500">☁️</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Clients() {
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [formData, setFormData] = useState({
    client_id: '', target_industries: '', hc_min: 10, hc_max: 500, t1_threshold: 70, t2_threshold: 40,
    route_to_hubspot: false, route_to_salesforce: false
  })

  useEffect(() => {
    fetchClients()
  }, [])

  const fetchClients = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/clients`)
      setClients(res.data)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      await axios.post(`${API_BASE}/admin/clients/add`, {
        client_id: formData.client_id,
        target_industries: formData.target_industries,
        hc_min: formData.hc_min,
        hc_max: formData.hc_max,
        t1_threshold: formData.t1_threshold,
        t2_threshold: formData.t2_threshold,
        route_to_hubspot: formData.route_to_hubspot,
        route_to_salesforce: formData.route_to_salesforce,
      })
      setShowModal(false)
      fetchClients()
    } catch (err) {
      alert('Failed to add client')
    }
  }

  if (loading) return <div>Loading...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">Clients</h1>
        <button onClick={() => setShowModal(true)} className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700">
          + Add Client
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {clients.map((client, i) => (
          <div key={i} className="bg-white p-6 rounded-lg shadow">
            <div className="flex justify-between items-start">
              <h3 className="text-xl font-bold">{client.client_id}</h3>
              <span className="text-gray-400 text-sm">{client.updated_at?.slice(0,10)}</span>
            </div>
            <div className="mt-4 space-y-2 text-sm">
              <div><span className="text-gray-500">Industries:</span> {client.target_industries?.join(', ')}</div>
              <div><span className="text-gray-500">Headcount:</span> {client.hc_min} - {client.hc_max}</div>
              <div><span className="text-gray-500">T1 Threshold:</span> {client.t1_threshold}</div>
              <div className="flex gap-4 mt-2">
                <span>HubSpot: {client.route_to_hubspot ? '✅' : '❌'}</span>
                <span>Salesforce: {client.route_to_salesforce ? '✅' : '❌'}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg">
            <h3 className="text-xl font-bold mb-4">Add New Client</h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div><label className="block text-sm font-medium">Client ID</label><input type="text" value={formData.client_id} onChange={e => setFormData({...formData, client_id: e.target.value})} className="w-full px-4 py-2 border rounded-lg" required /></div>
              <div><label className="block text-sm font-medium">Target Industries (comma separated)</label><input type="text" value={formData.target_industries} onChange={e => setFormData({...formData, target_industries: e.target.value})} placeholder="SaaS, MarTech" className="w-full px-4 py-2 border rounded-lg" required /></div>
              <div className="grid grid-cols-2 gap-4">
                <div><label className="block text-sm font-medium">Min Headcount</label><input type="number" value={formData.hc_min} onChange={e => setFormData({...formData, hc_min: parseInt(e.target.value)})} className="w-full px-4 py-2 border rounded-lg" /></div>
                <div><label className="block text-sm font-medium">Max Headcount</label><input type="number" value={formData.hc_max} onChange={e => setFormData({...formData, hc_max: parseInt(e.target.value)})} className="w-full px-4 py-2 border rounded-lg" /></div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div><label className="block text-sm font-medium">T1 Threshold</label><input type="number" value={formData.t1_threshold} onChange={e => setFormData({...formData, t1_threshold: parseInt(e.target.value)})} className="w-full px-4 py-2 border rounded-lg" /></div>
                <div><label className="block text-sm font-medium">T2 Threshold</label><input type="number" value={formData.t2_threshold} onChange={e => setFormData({...formData, t2_threshold: parseInt(e.target.value)})} className="w-full px-4 py-2 border rounded-lg" /></div>
              </div>
              <div className="flex gap-4">
                <label className="flex items-center"><input type="checkbox" checked={formData.route_to_hubspot} onChange={e => setFormData({...formData, route_to_hubspot: e.target.checked})} className="mr-2" /> Route to HubSpot</label>
                <label className="flex items-center"><input type="checkbox" checked={formData.route_to_salesforce} onChange={e => setFormData({...formData, route_to_salesforce: e.target.checked})} className="mr-2" /> Route to Salesforce</label>
              </div>
              <div className="flex gap-2 mt-4">
                <button type="submit" className="px-4 py-2 bg-purple-600 text-white rounded-lg">Save</button>
                <button type="button" onClick={() => setShowModal(false)} className="px-4 py-2 bg-gray-200 rounded-lg">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function Integrations() {
  const integrations = [
    { name: 'Apollo', icon: '🔍', key: 'APOLLO_API_KEY', desc: 'Lead enrichment and webhook integration' },
    { name: 'HubSpot', icon: '🟠', key: 'HUBSPOT_API_KEY', desc: 'Push leads to HubSpot contacts' },
    { name: 'Salesforce', icon: '☁️', key: 'SALESFORCE_ACCESS_TOKEN', desc: 'Push leads to Salesforce contacts' },
  ]

  const envVars = { APOLLO_API_KEY: import.meta.env.VITE_APOLLO_API_KEY, HUBSPOT_API_KEY: import.meta.env.VITE_HUBSPOT_API_KEY }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Integrations</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {integrations.map((int, i) => {
          const isSet = envVars[int.key]
          return (
            <div key={i} className="bg-white p-6 rounded-lg shadow">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-bold">{int.icon} {int.name}</h3>
                <span className={`px-3 py-1 rounded-full text-sm ${isSet ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                  {isSet ? 'Connected' : 'Not Connected'}
                </span>
              </div>
              <p className="text-gray-600 text-sm mb-4">{int.desc}</p>
              <div className="text-sm">
                <div className="flex justify-between py-2 border-b">
                  <span>API Key</span>
                  <span className={isSet ? 'text-green-500' : 'text-red-500'}>
                    {isSet ? 'Configured' : 'Set via Environment Variable'}
                  </span>
                </div>
              </div>
              {!isSet && <p className="text-xs text-gray-400 mt-2">Set {int.key} in Vercel environment variables</p>}
            </div>
          )
        })}
      </div>
      <div className="mt-8 bg-blue-50 p-4 rounded-lg">
        <h4 className="font-bold text-blue-800 mb-2">How to Configure</h4>
        <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
          <li>Go to Vercel project settings</li>
          <li>Navigate to Environment Variables</li>
          <li>Add required API keys</li>
          <li>Redeploy the application</li>
        </ol>
      </div>
    </div>
  )
}

function Logs() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchLogs()
  }, [])

  const fetchLogs = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/logs`)
      setLogs(res.data)
    } catch (err) {
      console.error(err)
    }
    setLoading(false)
  }

  if (loading) return <div>Loading...</div>

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Activity Logs</h1>
      <div className="bg-white rounded-lg shadow overflow-x">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left">Action</th>
              <th className="px-4 py-3 text-left">Details</th>
              <th className="px-4 py-3 text-left">Lead</th>
              <th className="px-4 py-3 text-left">Client</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">Time</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log, i) => (
              <tr key={i} className="border-t">
                <td className="px-4 py-3 font-medium">{log.action}</td>
                <td className="px-4 py-3 text-gray-600">{log.details || '-'}</td>
                <td className="px-4 py-3">{log.lead_id || '-'}</td>
                <td className="px-4 py-3">{log.client_id || '-'}</td>
                <td className={`px-4 py-3 ${log.status === 'success' ? 'text-green-600' : 'text-red-600'}`}>{log.status}</td>
                <td className="px-4 py-3 text-gray-500">{log.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Settings() {
  const { user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState('')

  const handlePasswordChange = async (e) => {
    e.preventDefault()
    if (newPassword !== confirmPassword) {
      setMessage('Passwords do not match')
      return
    }
    if (newPassword.length < 6) {
      setMessage('Password must be at least 6 characters')
      return
    }
    setMessage('Password change not available via frontend - use API')
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Settings</h1>
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-bold mb-4">Change Password</h3>
        <form onSubmit={handlePasswordChange} className="space-y-4">
          <div><label className="block text-sm font-medium">Current Password</label><input type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} className="w-full px-4 py-2 border rounded-lg" /></div>
          <div><label className="block text-sm font-medium">New Password</label><input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} className="w-full px-4 py-2 border rounded-lg" /></div>
          <div><label className="block text-sm font-medium">Confirm New Password</label><input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} className="w-full px-4 py-2 border rounded-lg" /></div>
          {message && <div className="p-3 bg-red-100 text-red-700 rounded-lg">{message}</div>}
          <button type="submit" className="px-6 py-2 bg-purple-600 text-white rounded-lg">Update Password</button>
        </form>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-bold mb-4">Environment Variables</h3>
        <div className="space-y-3">
          <div className="flex justify-between items-center py-2 border-b"><span className="font-medium">APOLLO_API_KEY</span><span className="text-gray-500">Set via Vercel</span></div>
          <div className="flex justify-between items-center py-2 border-b"><span className="font-medium">HUBSPOT_API_KEY</span><span className="text-gray-500">Set via Vercel</span></div>
          <div className="flex justify-between items-center py-2 border-b"><span className="font-medium">SALESFORCE_INSTANCE_URL</span><span className="text-gray-500">Set via Vercel</span></div>
          <div className="flex justify-between items-center py-2 border-b"><span className="font-medium">SALESFORCE_ACCESS_TOKEN</span><span className="text-gray-500">Set via Vercel</span></div>
        </div>
      </div>
    </div>
  )
}

export default App