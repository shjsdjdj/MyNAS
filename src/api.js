import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 60000, withCredentials: true })

export function classifyApiError(error, online = typeof navigator === 'undefined' ? true : navigator.onLine) {
  const status = error?.response?.status
  const serverCode = error?.response?.data?.error?.code
  if (status === 401 && !error?.config?.url?.includes('/auth/login')) return 'auth_expired'
  if (serverCode === 'database_error') return 'database_error'
  if (serverCode === 'storage_unavailable') return 'storage_unavailable'
  if (!error?.response && online === false) return 'network_error'
  if (!error?.response) return 'backend_offline'
  return null
}

export const getPublicHealth = () => axios.get('/health', {
  timeout: 4000,
  withCredentials: false,
  headers: { 'Cache-Control': 'no-cache' },
}).then(r => r.data)

export async function resolveConnectionFailure(error) {
  const reason = classifyApiError(error)
  if (reason && reason !== 'backend_offline') return reason
  if (error?.response && error.response.status < 500) return null
  try {
    const health = await getPublicHealth()
    if (health?.reason === 'database_error' || health?.database === 'error') return 'database_error'
    if (health?.reason === 'storage_unavailable' || health?.storage === 'unavailable') return 'storage_unavailable'
    return 'backend_error'
  } catch (probeError) {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'network_error'
    const payload = probeError?.response?.data
    if (payload?.reason === 'database_error') return 'database_error'
    if (payload?.reason === 'storage_unavailable') return 'storage_unavailable'
    return 'backend_offline'
  }
}

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      window.dispatchEvent(new CustomEvent('mynas-auth-required', { detail: { reason: 'auth_expired' } }))
    }
    return Promise.reject(error)
  },
)

export const login = (username, password) => api.post('/auth/login', { username, password }).then(r => r.data)
export const logout = () => api.post('/auth/logout').then(r => r.data)
export const getMe = () => api.get('/auth/me').then(r => r.data)
export const changePassword = (current_password, new_password) => api.post('/auth/change-password', { current_password, new_password }).then(r => r.data)
export const getDashboard = () => api.get('/dashboard').then(r => r.data)
export const getNetworkStatus = () => api.get('/network').then(r => r.data)
export const getFiles = parentId => api.get('/assets', { params: parentId ? { parent_id: parentId } : {} }).then(r => r.data)
export const uploadFiles = (parentId, files, onProgress) => {
  const form = new FormData()
  form.append('parent_id', parentId)
  files.forEach(file => form.append('files', file))
  return api.post('/upload', form, { onUploadProgress: onProgress }).then(r => r.data)
}
export const createFolder = (parentId, name) => api.post('/assets/folder', { parent_id: parentId, name }).then(r => r.data)
export const deleteFile = assetId => api.delete(`/assets/${assetId}`).then(r => r.data)
export const assetDownloadUrl = assetId => `/api/assets/${assetId}`
export const getPhotos = (page = 1, pageSize = 40) => api.get('/photos', { params: { page, page_size: pageSize } }).then(r => r.data)
export const getPhotoTimeline = (page = 1, pageSize = 60, filters = {}) => api.get('/photos/timeline', { params: { page, page_size: pageSize, ...filters } }).then(r => r.data)
export const getRecentPhotos = (page = 1, pageSize = 40) => api.get('/photos/recent', { params: { page, page_size: pageSize } }).then(r => r.data)
export const getFavoritePhotos = (page = 1, pageSize = 40) => api.get('/photos/favorites', { params: { page, page_size: pageSize } }).then(r => r.data)
export const searchPhotos = (query, page = 1, pageSize = 40) => api.get('/photos/search', { params: { q: query, page, page_size: pageSize } }).then(r => r.data)
export const setPhotoFavorite = (assetId, isFavorite) => api.patch(`/assets/${assetId}/favorite`, { is_favorite: isFavorite }).then(r => r.data)
export const getTrash = () => api.get('/trash').then(r => r.data)
export const restoreTrash = assetId => api.post(`/trash/${assetId}/restore`).then(r => r.data)
export const permanentDeleteTrash = assetId => api.delete(`/trash/${assetId}/permanent`).then(r => r.data)
export const emptyTrash = () => api.delete('/trash').then(r => r.data)
export const changeUsername = username => api.patch('/settings/account/username', { username }).then(r => r.data)
export const getPreferences = () => api.get('/settings/preferences').then(r => r.data)
export const savePreferences = preferences => api.patch('/settings/preferences', preferences).then(r => r.data)
export const getStorageLocations = () => api.get('/settings/storage').then(r => r.data)
export const addStorageLocation = payload => api.post('/settings/storage', payload).then(r => r.data)
export const updateStorageLocation = (id, payload) => api.patch(`/settings/storage/${id}`, payload).then(r => r.data)
export const deleteStorageLocation = id => api.delete(`/settings/storage/${id}`).then(r => r.data)
export const makeDefaultStorage = id => api.post(`/settings/storage/${id}/default`).then(r => r.data)
export const getBackupSettings = () => api.get('/settings/backup').then(r => r.data)
export const saveBackupSettings = payload => api.patch('/settings/backup', payload).then(r => r.data)
export const runBackupNow = () => api.post('/settings/backup/run').then(r => r.data)
export const getSystemInformation = () => api.get('/settings/system').then(r => r.data)
