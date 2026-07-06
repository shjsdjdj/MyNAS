<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  PhArchiveBox as ArchiveBox, PhArrowClockwise as ArrowClockwise,
  PhCaretRight as CaretRight, PhCloudArrowUp as CloudArrowUp,
  PhDatabase as Database, PhDownloadSimple as DownloadSimple,
  PhFile as File, PhFileText as FileText, PhFilmSlate as FilmSlate,
  PhFolder as Folder, PhFolderPlus as FolderPlus, PhGear as Gear,
  PhHardDrives as HardDrives, PhHouse as House, PhImage as Image,
  PhMagnifyingGlass as MagnifyingGlass, PhShieldCheck as ShieldCheck,
  PhTrash as Trash, PhUploadSimple as UploadSimple, PhX as X,
  PhCalendarBlank as CalendarBlank, PhClockCounterClockwise as ClockCounterClockwise,
  PhHeart as Heart, PhArrowLeft as ArrowLeft, PhArrowRight as ArrowRight,
  PhUser as UserIcon, PhGlobe as Globe, PhMapPin as MapPin,
  PhPencilSimple as PencilSimple, PhPlus as Plus, PhPlay as Play,
  PhSun as Sun, PhCheckSquare as CheckSquare, PhSquare as Square
} from '@phosphor-icons/vue'
import {
  addStorageLocation, assetDownloadUrl, changePassword, changeUsername,
  createFolder, deleteFile, deleteStorageLocation, emptyTrash,
  getBackupSettings,
  getDashboard, getFiles, getMe, getPhotoTimeline, getPhotos, getRecentPhotos,
  getPreferences, getStorageLocations, getSystemInformation, getTrash,
  login, logout, makeDefaultStorage, permanentDeleteTrash, restoreTrash,
  runBackupNow, saveBackupSettings, savePreferences, searchPhotos, setPhotoFavorite,
  updateStorageLocation, uploadFiles,
} from './api'
import { locale, setLocale, t } from './locales'

const nav = [
  { key: 'dashboard', labelKey: 'nav.dashboard', icon: House },
  { key: 'photos', labelKey: 'nav.photos', icon: Image },
  { key: 'timeline', labelKey: 'nav.timeline', icon: CalendarBlank },
  { key: 'recent', labelKey: 'nav.recent', icon: ClockCounterClockwise },
  { key: 'Videos', labelKey: 'nav.videos', icon: FilmSlate },
  { key: 'Documents', labelKey: 'nav.documents', icon: FileText },
  { key: 'Downloads', labelKey: 'nav.downloads', icon: DownloadSimple },
  { key: 'Backup', labelKey: 'nav.backup', icon: ArchiveBox },
  { key: 'trash', labelKey: 'nav.trash', icon: Trash },
]
const meta = {
  Photos: { labelKey: 'dashboard.photos', icon: Image, tone: 'cyan' },
  Videos: { labelKey: 'nav.videos', icon: FilmSlate, tone: 'violet' },
  Documents: { labelKey: 'nav.documents', icon: FileText, tone: 'blue' },
  Downloads: { labelKey: 'nav.downloads', icon: DownloadSimple, tone: 'orange' },
  Backup: { labelKey: 'nav.backup', icon: ArchiveBox, tone: 'purple' },
  trash: { labelKey: 'nav.trash', icon: Trash, tone: 'purple' },
  photos: { labelKey: 'photos.album', icon: Image, tone: 'cyan' },
  timeline: { labelKey: 'photos.timeline', icon: CalendarBlank, tone: 'blue' },
  recent: { labelKey: 'photos.recent', icon: ClockCounterClockwise, tone: 'violet' },
  settings: { labelKey: 'settings.title', icon: Gear, tone: 'blue' },
}
const photoKeys = new Set(['photos', 'timeline', 'recent'])
const routeMap = { dashboard: '/dashboard', photos: '/photos', timeline: '/photos/timeline', recent: '/photos/recent', settings: '/settings' }
const routeAliases = { '/timeline': 'timeline', '/recent': 'recent' }
const routeFromPath = () => {
  const path = window.location.pathname
  if (routeAliases[path]) return routeAliases[path]
  return Object.entries(routeMap).find(([, p]) => p === path)?.[0] || 'photos'
}
const current = ref(routeFromPath())
const currentFolderId = ref(null)
const folderBreadcrumbs = ref([])
const dashboard = ref(null)
const items = ref([])
const loading = ref(true)
const error = ref('')
const showUpload = ref(false)
const showNewFolder = ref(false)
const selectedFiles = ref([])
const uploadProgress = ref(0)
const folderName = ref('')
const search = ref('')
const user = ref(null)
const authReady = ref(false)
const loginForm = ref({ username: 'admin', password: '' })
const loginError = ref('')
const loginLoading = ref(false)
const passwordChangeRequired = ref(false)
const passwordForm = ref({ current: '', next: '', confirm: '' })
const passwordError = ref('')
const passwordLoading = ref(false)
const photoItems = ref([])
const timelineGroups = ref([])
const photoPage = ref(1)
const photoHasMore = ref(false)
const photoTotal = ref(0)
const photoLoading = ref(false)
const timelinePeriod = ref('')
const timelineDate = ref('')
const lightboxIndex = ref(-1)
const toast = ref(null)
const dragActive = ref(false)
const selectMode = ref(false)
const selectedPhotoIds = ref(new Set())
const highlightedPhotoId = ref(null)
const preferences = ref({ language: locale.value, theme: 'light', default_home: 'photos', default_upload_directory: 'Photos', photo_sort: 'taken_desc' })
const storageLocations = ref([])
const backupConfig = ref({ directory: '', enabled: false, daily_time: '02:00', last_backup_at: null, last_status: 'never' })
const systemInfo = ref(null)
const settingsLoading = ref(false)
const usernameDraft = ref('')
const storageDraft = ref({ name: '', path: '', is_default: false })
const editingStorageId = ref(null)
const backupRunning = ref(false)
let photoSearchTimer = null
let photoRequestId = 0

const isDashboard = computed(() => current.value === 'dashboard')
const isTrash = computed(() => current.value === 'trash')
const isPhotoView = computed(() => photoKeys.has(current.value))
const isSettings = computed(() => current.value === 'settings')
const lightboxPhoto = computed(() => lightboxIndex.value >= 0 ? photoItems.value[lightboxIndex.value] : null)
const title = computed(() => isDashboard.value ? t('dashboard.welcome') : t(meta[current.value]?.labelKey || 'files.title'))
const subtitle = computed(() => {
  if (isDashboard.value) return t('dashboard.subtitle')
  if (current.value === 'photos') return t('photos.albumSubtitle', { count: photoTotal.value })
  if (current.value === 'timeline') return t('photos.timelineSubtitle')
  if (current.value === 'recent') return t('photos.recentSubtitle')
  if (isSettings.value) return t('settings.subtitle')
  return `MyNAS / ${folderBreadcrumbs.value.map(item => item.filename).join(' / ')}`
})
const filteredItems = computed(() => items.value.filter(item => item.name.toLowerCase().includes(search.value.toLowerCase())))
const photosRootId = computed(() => dashboard.value?.categories?.find(item => item.name === 'Photos')?.id)
const defaultUploadRootId = computed(() => dashboard.value?.categories?.find(item => item.name === preferences.value.default_upload_directory)?.id || photosRootId.value)
const timelineYears = computed(() => [...new Set(timelineGroups.value.map(group => group.year))])
const timelineMonths = computed(() => [...new Set(timelineGroups.value.map(group => group.date.slice(0, 7)))])
const fallbackCategoryMeta = { icon: Folder, tone: 'blue' }

function categoryMeta(name) { return meta[name] || fallbackCategoryMeta }
function categoryLabel(name) { return meta[name]?.labelKey ? t(meta[name].labelKey) : name }

function mergePhotoItems(incoming, reset = false) {
  if (!reset) {
    const existingIds = new Set(photoItems.value.map(item => item.id))
    photoItems.value = [...photoItems.value, ...incoming.filter(item => !existingIds.has(item.id))]
    return
  }
  photoItems.value = [...new Map(incoming.map(item => [item.id, item])).values()]
}

function friendlyError(e, fallback = 'errors.generic') {
  if (!e.response) return t('errors.network')
  return ({ 401: t('errors.unauthorized'), 403: t('errors.forbidden'), 404: t('errors.notFound'), 409: t('errors.conflict'), 422: t('errors.validation') })[e.response.status] || t(fallback)
}
function showToast(message, type = 'success') {
  toast.value = { message, type }
  window.setTimeout(() => { toast.value = null }, 3500)
}

async function loadDashboard() {
  loading.value = true; error.value = ''
  try { dashboard.value = await getDashboard() }
  catch (e) { error.value = friendlyError(e) }
  finally { loading.value = false }
}
async function loadFolder(folderId = currentFolderId.value) {
  currentFolderId.value = folderId; loading.value = true; error.value = ''
  try {
    const data = await getFiles(folderId)
    items.value = data.items
    folderBreadcrumbs.value = data.breadcrumbs || []
  }
  catch (e) { error.value = friendlyError(e) }
  finally { loading.value = false }
}
async function loadTrash() {
  loading.value = true; error.value = ''
  try {
    const data = await getTrash()
    items.value = data.items || []
    folderBreadcrumbs.value = [{ id: 'trash', filename: t('trash.title') }]
  } catch (e) { error.value = friendlyError(e) }
  finally { loading.value = false }
}
async function loadPhotoView(reset = true) {
  const requestId = ++photoRequestId
  if (reset) { photoPage.value = 1; photoItems.value = []; timelineGroups.value = [] }
  photoLoading.value = true; error.value = ''
  try {
    let data
    if (search.value.trim()) {
      data = await searchPhotos(search.value.trim(), photoPage.value, 40)
      if (requestId !== photoRequestId) return
      timelineGroups.value = []
      mergePhotoItems(data.items || [], reset)
    } else if (current.value === 'timeline') {
      const filters = timelinePeriod.value ? { period: timelinePeriod.value } : (timelineDate.value ? { date_from: timelineDate.value, date_to: timelineDate.value } : {})
      data = await getPhotoTimeline(photoPage.value, 60, filters)
      if (requestId !== photoRequestId) return
      const incoming = data.groups || []
      if (!reset && timelineGroups.value.length && incoming.length && timelineGroups.value.at(-1).date === incoming[0].date) {
        timelineGroups.value.at(-1).items.push(...incoming[0].items)
        timelineGroups.value.push(...incoming.slice(1))
      } else timelineGroups.value.push(...incoming)
      photoItems.value = timelineGroups.value.flatMap(group => group.items)
    } else {
      data = current.value === 'recent' ? await getRecentPhotos(photoPage.value, 40) : await getPhotos(photoPage.value, 40)
      if (requestId !== photoRequestId) return
      mergePhotoItems(data.items || [], reset)
    }
    photoHasMore.value = Boolean(data.has_more)
    photoTotal.value = data.total || 0
  } catch (e) { error.value = friendlyError(e) }
  finally { if (requestId === photoRequestId) photoLoading.value = false }
}
async function loadMorePhotos() {
  if (!photoHasMore.value || photoLoading.value) return
  photoPage.value += 1
  await loadPhotoView(false)
}
async function selectNav(key, pushHistory = true) {
  current.value = key; search.value = ''
  if (pushHistory && routeMap[key] && window.location.pathname !== routeMap[key]) window.history.pushState({}, '', routeMap[key])
  if (key === 'dashboard') await loadDashboard()
  else if (photoKeys.has(key)) await loadPhotoView()
  else if (key === 'settings') await loadSettings()
  else if (key === 'trash') await loadTrash()
  else {
    if (!dashboard.value) await loadDashboard()
    const root = dashboard.value?.categories?.find(item => item.name === key)
    if (!root) { error.value = t('errors.notFound'); return }
    await loadFolder(root.id)
  }
}
function refreshCurrent() {
  if (isDashboard.value) return loadDashboard()
  if (isPhotoView.value) return loadPhotoView()
  if (isSettings.value) return loadSettings()
  if (isTrash.value) return loadTrash()
  return loadFolder()
}
async function openItem(item) {
  if (item.is_directory) await loadFolder(item.id)
  else window.open(assetDownloadUrl(item.id), '_blank')
}
async function submitUpload() {
  if (!selectedFiles.value.length) return
  uploadProgress.value = 1
  try {
    const targetId = isPhotoView.value ? photosRootId.value : (isDashboard.value ? defaultUploadRootId.value : currentFolderId.value)
    const result = await uploadFiles(targetId, selectedFiles.value, event => {
      uploadProgress.value = Math.round((event.loaded / (event.total || event.loaded)) * 100)
    })
    const created = result.assets || result.uploaded || []
    highlightedPhotoId.value = created.at(-1)?.id || null
    showUpload.value = false; selectedFiles.value = []; uploadProgress.value = 0
    if (isPhotoView.value) await loadPhotoView()
    else if (isDashboard.value) await loadDashboard()
    else await loadFolder()
    showToast(t('upload.complete', { count: created.length }))
    await nextTick()
    if (highlightedPhotoId.value) document.querySelector(`[data-photo-id="${highlightedPhotoId.value}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  } catch (e) { showToast(t('upload.failed', { reason: friendlyError(e) }), 'error') }
}
async function submitFolder() {
  if (!folderName.value.trim()) return
  try {
    await createFolder(currentFolderId.value, folderName.value.trim())
    showNewFolder.value = false; folderName.value = ''; await loadFolder()
  } catch (e) { error.value = friendlyError(e) }
}
async function remove(item) {
  if (!confirm(t('files.deleteConfirm', { name: item.name }))) return
  try { await deleteFile(item.id); await loadFolder() }
  catch (e) { error.value = friendlyError(e) }
}
async function restoreItem(item) {
  try { await restoreTrash(item.id); await loadTrash() }
  catch (e) { error.value = friendlyError(e) }
}
async function permanentlyRemove(item) {
  if (!confirm(t('files.permanentConfirm', { name: item.name }))) return
  try { await permanentDeleteTrash(item.id); await loadTrash() }
  catch (e) { error.value = friendlyError(e) }
}
async function clearTrash() {
  if (!items.value.length || !confirm(t('trash.clearConfirm'))) return
  try { await emptyTrash(); await loadTrash() }
  catch (e) { error.value = friendlyError(e) }
}
function chooseFiles(event) { selectedFiles.value = [...event.target.files] }
function dropFiles(event) { dragActive.value = false; selectedFiles.value = [...event.dataTransfer.files]; showUpload.value = true }
function goBreadcrumb(index) { loadFolder(folderBreadcrumbs.value[index].id) }
function formatDate(value) { return value ? new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : t('common.never') }
function formatPhotoDay(value) { return new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(value)) }
function formatSession(value) { return value ? formatDate(new Date(value * 1000)) : '—' }
function openLightbox(item) { lightboxIndex.value = photoItems.value.findIndex(photo => photo.id === item.id) }
function closeLightbox() { lightboxIndex.value = -1 }
function stepLightbox(direction) {
  if (!photoItems.value.length) return
  lightboxIndex.value = (lightboxIndex.value + direction + photoItems.value.length) % photoItems.value.length
}
async function toggleFavorite(item) {
  try {
    const updated = await setPhotoFavorite(item.id, !item.is_favorite)
    item.is_favorite = updated.is_favorite
    if (lightboxPhoto.value?.id === item.id) lightboxPhoto.value.is_favorite = updated.is_favorite
  } catch (e) { error.value = friendlyError(e) }
}
async function applyTimelineFilter(period = '') {
  timelinePeriod.value = period
  if (period) timelineDate.value = ''
  await loadPhotoView()
}
function handleKeydown(event) {
  if (!lightboxPhoto.value) return
  if (event.key === 'Escape') closeLightbox()
  if (event.key === 'ArrowLeft') stepLightbox(-1)
  if (event.key === 'ArrowRight') stepLightbox(1)
}
function togglePhotoSelection(item) {
  const next = new Set(selectedPhotoIds.value)
  next.has(item.id) ? next.delete(item.id) : next.add(item.id)
  selectedPhotoIds.value = next
}
function leaveSelectMode() { selectMode.value = false; selectedPhotoIds.value = new Set() }
async function batchFavorite() {
  try {
    await Promise.all(photoItems.value.filter(item => selectedPhotoIds.value.has(item.id)).map(item => setPhotoFavorite(item.id, true)))
    showToast(t('settings.saved')); leaveSelectMode(); await loadPhotoView()
  } catch (e) { showToast(friendlyError(e), 'error') }
}
async function batchDelete() {
  if (!selectedPhotoIds.value.size || !confirm(t('photos.deleteConfirm'))) return
  try {
    await Promise.all([...selectedPhotoIds.value].map(id => deleteFile(id)))
    showToast(t('common.success')); leaveSelectMode(); await loadPhotoView()
  } catch (e) { showToast(friendlyError(e), 'error') }
}
function batchDownload() {
  photoItems.value.filter(item => selectedPhotoIds.value.has(item.id)).forEach((item, index) => {
    window.setTimeout(() => {
      const link = document.createElement('a'); link.href = assetDownloadUrl(item.id); link.download = item.name; link.click()
    }, index * 180)
  })
}
function jumpTimeline(value, type) {
  const group = timelineGroups.value.find(item => type === 'year' ? item.year === value : item.date.startsWith(value))
  if (group) document.getElementById(`day-${group.date}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
async function loadSettings() {
  settingsLoading.value = true; error.value = ''
  try {
    const [nextPreferences, storage, backup, system] = await Promise.all([
      getPreferences(), getStorageLocations(), getBackupSettings(), getSystemInformation(),
    ])
    preferences.value = nextPreferences
    storageLocations.value = storage.items || []
    backupConfig.value = backup
    systemInfo.value = system
    usernameDraft.value = user.value.username
    setLocale(nextPreferences.language)
  } catch (e) { error.value = friendlyError(e) }
  finally { settingsLoading.value = false }
}
async function persistPreferences() {
  try {
    preferences.value = await savePreferences(preferences.value)
    setLocale(preferences.value.language)
    document.documentElement.dataset.theme = preferences.value.theme
    showToast(t('settings.saved'))
  } catch (e) { showToast(friendlyError(e), 'error') }
}
async function persistUsername() {
  try {
    user.value = { ...user.value, ...(await changeUsername(usernameDraft.value)) }
    showToast(t('settings.saved'))
  } catch (e) { showToast(friendlyError(e), 'error') }
}
function beginStorageEdit(location) {
  editingStorageId.value = location.id
  storageDraft.value = { name: location.name, path: location.path, is_default: location.is_default }
}
function resetStorageDraft() { editingStorageId.value = null; storageDraft.value = { name: '', path: '', is_default: false } }
async function persistStorage() {
  try {
    if (editingStorageId.value) await updateStorageLocation(editingStorageId.value, { name: storageDraft.value.name, path: storageDraft.value.path })
    else await addStorageLocation(storageDraft.value)
    resetStorageDraft(); storageLocations.value = (await getStorageLocations()).items; showToast(t('settings.saved'))
  } catch (e) { showToast(friendlyError(e), 'error') }
}
async function removeStorageLocation(location) {
  if (!confirm(`${t('common.delete')} ${location.name}?`)) return
  try { await deleteStorageLocation(location.id); storageLocations.value = (await getStorageLocations()).items; showToast(t('common.success')) }
  catch (e) { showToast(friendlyError(e), 'error') }
}
async function chooseDefaultStorage(location) {
  try { await makeDefaultStorage(location.id); storageLocations.value = (await getStorageLocations()).items; showToast(t('settings.saved')) }
  catch (e) { showToast(friendlyError(e), 'error') }
}
async function persistBackup() {
  try { backupConfig.value = await saveBackupSettings(backupConfig.value); showToast(t('settings.saved')) }
  catch (e) { showToast(friendlyError(e), 'error') }
}
async function triggerBackup() {
  backupRunning.value = true
  try { await runBackupNow(); backupConfig.value = await getBackupSettings(); showToast(t('common.success')) }
  catch (e) { showToast(friendlyError(e), 'error') }
  finally { backupRunning.value = false }
}
async function enterInitialView() {
  await loadDashboard()
  try {
    preferences.value = await getPreferences()
    setLocale(preferences.value.language)
  } catch { /* defaults remain available */ }
  const requested = routeFromPath()
  await selectNav(window.location.pathname === '/' ? preferences.value.default_home : requested, false)
}
async function bootstrapAuth() {
  try {
    user.value = await getMe()
    passwordChangeRequired.value = Boolean(user.value.password_change_required)
    if (!passwordChangeRequired.value) await enterInitialView()
  }
  catch { user.value = null }
  finally { authReady.value = true }
}
async function submitLogin() {
  loginLoading.value = true; loginError.value = ''
  try {
    const result = await login(loginForm.value.username, loginForm.value.password)
    user.value = result.user
    passwordChangeRequired.value = Boolean(result.password_change_required)
    passwordForm.value.current = loginForm.value.password
    loginForm.value.password = ''
    if (!passwordChangeRequired.value) await enterInitialView()
  } catch (e) { loginError.value = friendlyError(e, 'auth.loginFailed') }
  finally { loginLoading.value = false }
}
async function submitPasswordChange() {
  passwordError.value = ''
  if (passwordForm.value.next !== passwordForm.value.confirm) {
    passwordError.value = t('auth.mismatch')
    return
  }
  passwordLoading.value = true
  try {
    await changePassword(passwordForm.value.current, passwordForm.value.next)
    passwordForm.value = { current: '', next: '', confirm: '' }
    passwordChangeRequired.value = false
    await enterInitialView()
    showToast(t('auth.passwordChanged'))
  } catch (e) { passwordError.value = friendlyError(e) }
  finally { passwordLoading.value = false }
}
async function handleLogout() {
  try { await logout() } finally { user.value = null; dashboard.value = null; passwordChangeRequired.value = false; current.value = 'photos' }
}
window.addEventListener('mynas-auth-required', () => { user.value = null })
window.addEventListener('keydown', handleKeydown)
window.addEventListener('popstate', () => { if (user.value) selectNav(routeFromPath(), false) })
watch(search, () => {
  if (!isPhotoView.value || !user.value) return
  window.clearTimeout(photoSearchTimer)
  photoSearchTimer = window.setTimeout(() => loadPhotoView(), 250)
})
onMounted(bootstrapAuth)
onBeforeUnmount(() => {
  window.clearTimeout(photoSearchTimer)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div v-if="!authReady" class="login-screen"><ArrowClockwise class="spin" :size="34" /></div>
  <div v-else-if="!user" class="login-screen">
    <section class="login-card">
      <div class="login-brand"><span class="brand-mark"><HardDrives :size="24" weight="fill" /></span><span>{{ t('secureName') }}</span></div>
      <h1>{{ t('auth.title') }}</h1>
      <p>{{ t('auth.subtitle') }}</p>
      <form class="login-form" @submit.prevent="submitLogin">
        <label>{{ t('auth.username') }}<input v-model="loginForm.username" autocomplete="username" required /></label>
        <label>{{ t('auth.password') }}<input v-model="loginForm.password" type="password" autocomplete="current-password" required /></label>
        <div v-if="loginError" class="login-error">{{ loginError }}</div>
        <button class="primary wide" :disabled="loginLoading">{{ loginLoading ? t('auth.loggingIn') : t('auth.login') }}</button>
      </form>
      <small class="login-hint">{{ t('auth.firstLogin') }}</small>
    </section>
  </div>
  <div v-else-if="passwordChangeRequired" class="login-screen">
    <section class="login-card">
      <div class="login-brand"><span class="brand-mark"><ShieldCheck :size="24" weight="fill" /></span><span>{{ t('secureName') }}</span></div>
      <h1>{{ t('auth.changeDefaultTitle') }}</h1>
      <p>{{ t('auth.changeDefaultText') }}</p>
      <form class="login-form" @submit.prevent="submitPasswordChange">
        <label>{{ t('auth.currentPassword') }}<input v-model="passwordForm.current" type="password" autocomplete="current-password" required /></label>
        <label>{{ t('auth.newPassword') }}<input v-model="passwordForm.next" type="password" autocomplete="new-password" minlength="8" required /></label>
        <label>{{ t('auth.confirmPassword') }}<input v-model="passwordForm.confirm" type="password" autocomplete="new-password" minlength="8" required /></label>
        <div v-if="passwordError" class="login-error">{{ passwordError }}</div>
        <button class="primary wide" :disabled="passwordLoading">{{ passwordLoading ? t('auth.saving') : t('auth.setPassword') }}</button>
      </form>
    </section>
  </div>
  <div v-else class="app-shell" @dragenter.prevent="dragActive = true" @dragover.prevent @dragleave.self="dragActive = false" @drop.prevent="dropFiles">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark"><HardDrives :size="24" weight="fill" /></span><span>MyNAS</span></div>
      <nav>
        <button v-for="item in nav" :key="item.key" :class="['nav-item', { active: current === item.key }]" @click="selectNav(item.key)">
          <component :is="item.icon" :size="20" /><span>{{ t(item.labelKey) }}</span>
        </button>
      </nav>
      <div class="nav-bottom"><button class="nav-item" @click="selectNav('settings')"><ShieldCheck :size="20" /><span>{{ t('nav.security') }}</span></button><button :class="['nav-item', { active: current === 'settings' }]" @click="selectNav('settings')"><Gear :size="20" /><span>{{ t('nav.settings') }}</span></button></div>
      <div class="device-card"><span class="device-icon"><Database :size="20" /></span><div><strong>{{ t('dashboard.storage') }}</strong><small>Asset + UUID</small></div><i></i></div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div><p class="eyebrow">{{ t('personalCloud') }}</p><h1>{{ title }}</h1><p class="subtitle">{{ subtitle }}</p></div>
        <div class="top-actions"><label v-if="!isSettings" class="search"><MagnifyingGlass :size="19" /><input v-model="search" :placeholder="isPhotoView ? t('photos.filter') : t('files.search')" /></label><button class="icon-button" :title="t('common.refresh')" @click="refreshCurrent"><ArrowClockwise :size="20" /></button><button class="avatar" :title="t('common.logout')" @click="handleLogout">{{ user.username.slice(0, 1).toUpperCase() }}</button></div>
      </header>
      <div v-if="error" class="error-banner"><span>{{ error }}</span><button @click="error = ''"><X :size="18" /></button></div>

      <template v-if="isPhotoView">
        <section class="photo-toolbar">
          <div class="photo-tabs">
            <button :class="{ active: current === 'photos' }" @click="selectNav('photos')">{{ t('photos.all') }}</button>
            <button :class="{ active: current === 'timeline' }" @click="selectNav('timeline')">{{ t('photos.timeline') }}</button>
            <button :class="{ active: current === 'recent' }" @click="selectNav('recent')">{{ t('photos.recent') }}</button>
          </div>
          <div class="photo-toolbar-actions">
            <template v-if="current === 'timeline'">
              <button :class="['filter-chip', { active: timelinePeriod === 'today' }]" @click="applyTimelineFilter('today')">{{ t('photos.today') }}</button>
              <button :class="['filter-chip', { active: timelinePeriod === '7d' }]" @click="applyTimelineFilter('7d')">{{ t('photos.sevenDays') }}</button>
              <label class="date-jump"><CalendarBlank :size="16" /><input v-model="timelineDate" type="date" @change="applyTimelineFilter('')" /></label>
              <select class="jump-select" :aria-label="t('photos.jumpYear')" @change="jumpTimeline($event.target.value, 'year')"><option value="">{{ t('photos.jumpYear') }}</option><option v-for="year in timelineYears" :key="year">{{ year }}</option></select>
              <select class="jump-select" :aria-label="t('photos.jumpMonth')" @change="jumpTimeline($event.target.value, 'month')"><option value="">{{ t('photos.jumpMonth') }}</option><option v-for="month in timelineMonths" :key="month">{{ month }}</option></select>
            </template>
            <template v-if="selectMode">
              <span class="selection-count">{{ t('photos.selected', { count: selectedPhotoIds.size }) }}</span>
              <button class="secondary" :disabled="!selectedPhotoIds.size" @click="batchFavorite"><Heart :size="17" />{{ t('photos.batchFavorite') }}</button>
              <button class="secondary" :disabled="!selectedPhotoIds.size" @click="batchDownload"><DownloadSimple :size="17" />{{ t('photos.batchDownload') }}</button>
              <button class="secondary danger" :disabled="!selectedPhotoIds.size" @click="batchDelete"><Trash :size="17" />{{ t('photos.batchDelete') }}</button>
              <button class="secondary" @click="leaveSelectMode">{{ t('photos.done') }}</button>
            </template>
            <button v-else class="secondary" @click="selectMode = true"><CheckSquare :size="17" />{{ t('photos.select') }}</button>
            <button class="primary" @click="showUpload = true"><UploadSimple :size="18" /> {{ t('photos.upload') }}</button>
          </div>
        </section>

        <section class="photo-library">
          <div v-if="photoLoading && !photoItems.length" class="photo-loading"><ArrowClockwise class="spin" :size="32" /><span>{{ t('photos.arranging') }}</span></div>
          <div v-else-if="!photoItems.length" class="photo-empty"><Image :size="52" weight="duotone" /><strong>{{ t('photos.empty') }}</strong><p>{{ t('photos.emptyText') }}</p><button class="primary" @click="showUpload = true"><UploadSimple :size="18" /> {{ t('photos.uploadFirst') }}</button></div>

          <template v-else-if="current === 'timeline' && !search.trim()">
            <section v-for="group in timelineGroups" :id="`day-${group.date}`" :key="group.date" class="timeline-day">
              <div class="timeline-date"><span>{{ group.day }}</span><div><strong>{{ formatPhotoDay(group.date) }}</strong><small>{{ t('photos.count', { count: group.items.length }) }}</small></div></div>
              <div class="photo-masonry compact">
                <article v-for="item in group.items" :key="item.id" :data-photo-id="item.id" :class="['library-photo', { selected: selectedPhotoIds.has(item.id), highlighted: highlightedPhotoId === item.id }]" @click="selectMode ? togglePhotoSelection(item) : openLightbox(item)">
                  <img v-if="item.thumbnail_url" :src="item.thumbnail_url" :alt="item.name" loading="lazy" :width="item.width || 480" :height="item.height || 360" />
                  <span v-else class="photo-placeholder"><Image :size="30" weight="duotone" /></span>
                  <button v-if="selectMode" class="select-photo-button" @click.stop="togglePhotoSelection(item)"><CheckSquare v-if="selectedPhotoIds.has(item.id)" :size="21" weight="fill" /><Square v-else :size="21" /></button>
                  <button v-else :class="['favorite-button', { active: item.is_favorite }]" :title="item.is_favorite ? t('photos.unfavorite') : t('photos.favorite')" @click.stop="toggleFavorite(item)"><Heart :size="18" :weight="item.is_favorite ? 'fill' : 'bold'" /></button>
                  <span class="photo-time">{{ new Date(item.taken_at).toLocaleTimeString(locale === 'zh' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' }) }}</span>
                </article>
              </div>
            </section>
          </template>

          <div v-else class="photo-masonry">
            <article v-for="item in photoItems" :key="item.id" :data-photo-id="item.id" :class="['library-photo', { selected: selectedPhotoIds.has(item.id), highlighted: highlightedPhotoId === item.id }]" @click="selectMode ? togglePhotoSelection(item) : openLightbox(item)">
              <img v-if="item.thumbnail_url" :src="item.thumbnail_url" :alt="item.name" loading="lazy" :width="item.width || 480" :height="item.height || 360" />
              <span v-else class="photo-placeholder"><Image :size="30" weight="duotone" /></span>
              <button v-if="selectMode" class="select-photo-button" @click.stop="togglePhotoSelection(item)"><CheckSquare v-if="selectedPhotoIds.has(item.id)" :size="21" weight="fill" /><Square v-else :size="21" /></button>
              <button v-else :class="['favorite-button', { active: item.is_favorite }]" :title="item.is_favorite ? t('photos.unfavorite') : t('photos.favorite')" @click.stop="toggleFavorite(item)"><Heart :size="18" :weight="item.is_favorite ? 'fill' : 'bold'" /></button>
              <div class="photo-caption"><strong>{{ item.name }}</strong><span>{{ formatPhotoDay(item.taken_at) }}</span></div>
            </article>
          </div>

          <div v-if="photoHasMore" class="load-more"><button class="secondary" :disabled="photoLoading" @click="loadMorePhotos"><ArrowClockwise v-if="photoLoading" class="spin" :size="17" />{{ photoLoading ? t('photos.loadingMore') : t('photos.loadMore') }}</button></div>
        </section>
      </template>

      <template v-else-if="isDashboard">
        <section class="hero-card">
          <div><span class="hero-kicker"><ShieldCheck :size="16" weight="fill" /> {{ t('dashboard.secure') }}</span><h2>{{ t('dashboard.heroTitle') }}</h2><p>{{ t('dashboard.heroText') }}</p><button class="primary" @click="showUpload = true"><CloudArrowUp :size="20" weight="bold" /> {{ t('dashboard.upload') }}</button></div>
          <div class="storage-ring" :style="{ '--percent': `${dashboard?.disk.percent || 0}%` }"><div><strong>{{ dashboard?.disk.percent || 0 }}%</strong><span>{{ t('dashboard.used') }}</span></div></div>
          <div class="storage-copy"><small>{{ t('dashboard.storage') }}</small><strong>{{ dashboard?.disk.used_label || '0 B' }} / {{ dashboard?.disk.total_label || '—' }}</strong><span>{{ t('dashboard.remaining') }} {{ dashboard?.disk.free_label || '—' }}</span></div>
        </section>

        <section class="dashboard-stats">
          <article><Image :size="22" /><span><small>{{ t('dashboard.photos') }}</small><strong>{{ dashboard?.stats.photo_count || 0 }}</strong></span></article>
          <article><FilmSlate :size="22" /><span><small>{{ t('dashboard.videos') }}</small><strong>{{ dashboard?.stats.video_count || 0 }}</strong></span></article>
          <article><FileText :size="22" /><span><small>{{ t('dashboard.files') }}</small><strong>{{ dashboard?.stats.file_count || 0 }}</strong></span></article>
          <article><Heart :size="22" /><span><small>{{ t('dashboard.favorites') }}</small><strong>{{ dashboard?.stats.favorite_count || 0 }}</strong></span></article>
          <article><ArchiveBox :size="22" /><span><small>{{ t('dashboard.backupStatus') }}</small><strong>{{ dashboard?.backup.status || t('common.never') }}</strong></span></article>
          <article><ShieldCheck :size="22" /><span><small>{{ t('dashboard.systemHealth') }}</small><strong>{{ t('dashboard.healthy') }}</strong></span></article>
        </section>

        <section class="section-block">
          <div class="section-heading"><div><h2>{{ t('dashboard.recentPhotos') }}</h2><p>{{ t('photos.recentSubtitle') }}</p></div><button class="text-button" @click="selectNav('recent')">{{ t('photos.recent') }} <CaretRight :size="16" /></button></div>
          <div v-if="dashboard?.recent_photos?.length" class="recent-photo-strip"><button v-for="photo in dashboard.recent_photos" :key="photo.id" @click="selectNav('recent')"><img v-if="photo.thumbnail_url" :src="photo.thumbnail_url" :alt="photo.name" loading="lazy" /><span v-else><Image :size="25" weight="duotone" /></span></button></div>
          <div v-else class="empty-mini"><Image :size="32" /><span>{{ t('photos.empty') }}</span></div>
        </section>

        <section class="section-block">
          <div class="section-heading"><div><h2>{{ t('dashboard.overview') }}</h2><p>{{ t('dashboard.subtitle') }}</p></div><button class="text-button" @click="selectNav('photos')">{{ t('dashboard.openAlbum') }} <CaretRight :size="16" /></button></div>
          <div class="category-grid">
            <button v-for="cat in dashboard?.categories || []" :key="cat.name" class="category-card" @click="selectNav(cat.name === 'Photos' ? 'photos' : cat.name)">
              <span :class="['category-icon', categoryMeta(cat.name).tone]"><component :is="categoryMeta(cat.name).icon" :size="26" weight="fill" /></span>
              <span><strong>{{ categoryLabel(cat.name) }}</strong><small>{{ cat.count }} {{ t('dashboard.files') }}</small></span><b>{{ cat.size_label }}</b><CaretRight class="card-arrow" :size="18" />
            </button>
          </div>
        </section>

        <section class="dashboard-grid">
          <div class="panel"><div class="section-heading compact"><div><h2>{{ t('dashboard.recentActivity') }}</h2><p>{{ t('dashboard.activityHint') }}</p></div></div>
            <div v-if="!dashboard?.activities?.length" class="empty-mini"><ArchiveBox :size="32" /><span>{{ t('dashboard.noActivity') }}</span></div>
            <div v-for="activity in dashboard?.activities" :key="activity.id" class="activity-row"><span class="activity-icon"><File :size="18" /></span><span><strong>{{ activity.action }} · {{ activity.target.split('/').at(-1) }}</strong><small>{{ activity.target }}</small></span><time>{{ formatDate(activity.created_at) }}</time></div>
          </div>
          <div class="panel quick-panel"><div class="section-heading compact"><div><h2>{{ t('dashboard.backupStatus') }}</h2><p>{{ formatDate(dashboard?.backup.finished_at) }}</p></div></div>
            <button @click="showUpload = true"><UploadSimple :size="21" /><span><strong>{{ t('dashboard.upload') }}</strong><small>{{ preferences.default_upload_directory }}</small></span><CaretRight :size="17" /></button>
            <button @click="selectNav('settings')"><Gear :size="21" /><span><strong>{{ t('settings.title') }}</strong><small>{{ t('settings.subtitle') }}</small></span><CaretRight :size="17" /></button>
          </div>
        </section>
      </template>

      <template v-else-if="isSettings">
        <div v-if="settingsLoading" class="settings-loading"><ArrowClockwise class="spin" :size="30" /><span>{{ t('common.loading') }}</span></div>
        <div v-else class="settings-layout">
          <section class="settings-card account-card">
            <header><span><UserIcon :size="22" /></span><div><h2>{{ t('settings.account') }}</h2><p>{{ t('settings.accountText') }}</p></div></header>
            <div class="settings-fields two-columns">
              <label>{{ t('settings.username') }}<div class="inline-input"><input v-model="usernameDraft" /><button class="secondary" @click="persistUsername">{{ t('common.save') }}</button></div></label>
              <label>{{ t('settings.role') }}<div class="read-only-value">{{ user.is_admin ? t('settings.administrator') : 'User' }}</div></label>
            </div>
            <div class="session-grid">
              <span><small>{{ t('settings.issuedAt') }}</small><strong>{{ formatSession(user.session?.issued_at) }}</strong></span>
              <span><small>{{ t('settings.expiresAt') }}</small><strong>{{ formatSession(user.session?.expires_at) }}</strong></span>
              <span><small>{{ t('settings.authType') }}</small><strong>{{ user.session?.auth_type || 'cookie' }}</strong></span>
            </div>
            <form class="password-settings" @submit.prevent="submitPasswordChange">
              <input v-model="passwordForm.current" type="password" :placeholder="t('auth.currentPassword')" required />
              <input v-model="passwordForm.next" type="password" :placeholder="t('auth.newPassword')" minlength="8" required />
              <input v-model="passwordForm.confirm" type="password" :placeholder="t('auth.confirmPassword')" minlength="8" required />
              <button class="secondary" :disabled="passwordLoading">{{ t('settings.changePassword') }}</button>
            </form>
            <button class="text-danger" @click="handleLogout">{{ t('common.logout') }}</button>
          </section>

          <section class="settings-card language-card">
            <header><span><Globe :size="22" /></span><div><h2>{{ t('settings.language') }}</h2><p>{{ t('settings.languageText') }}</p></div></header>
            <div class="segmented-control"><button :class="{ active: preferences.language === 'zh' }" @click="preferences.language = 'zh'; persistPreferences()">{{ t('settings.chinese') }}</button><button :class="{ active: preferences.language === 'en' }" @click="preferences.language = 'en'; persistPreferences()">{{ t('settings.english') }}</button></div>
          </section>

          <section class="settings-card storage-card wide-card">
            <header><span><HardDrives :size="22" /></span><div><h2>{{ t('settings.storage') }}</h2><p>{{ t('settings.storageText') }}</p></div></header>
            <div class="storage-list">
              <article v-for="location in storageLocations" :key="location.id" class="storage-location">
                <span class="storage-location-icon"><MapPin :size="21" /></span>
                <div><strong>{{ location.name }} <em v-if="location.is_default">{{ t('common.default') }}</em></strong><small>{{ location.path }}</small><div class="capacity-bar"><i :style="{ width: `${location.capacity.percent || 0}%` }"></i></div><small>{{ location.capacity.available ? `${t('settings.free')} ${location.capacity.free_label} / ${location.capacity.total_label}` : t('common.unavailable') }}</small></div>
                <div class="storage-actions"><button v-if="!location.is_default" :title="t('common.setDefault')" @click="chooseDefaultStorage(location)"><ShieldCheck :size="18" /></button><button :title="t('common.edit')" @click="beginStorageEdit(location)"><PencilSimple :size="18" /></button><button v-if="!location.is_default" :title="t('common.delete')" @click="removeStorageLocation(location)"><Trash :size="18" /></button></div>
              </article>
            </div>
            <form class="storage-form" @submit.prevent="persistStorage"><input v-model="storageDraft.name" :placeholder="t('settings.storageName')" required /><input v-model="storageDraft.path" :placeholder="t('settings.storagePath')" required /><button class="primary"><Plus v-if="!editingStorageId" :size="17" />{{ editingStorageId ? t('common.save') : t('settings.addStorage') }}</button><button v-if="editingStorageId" type="button" class="secondary" @click="resetStorageDraft">{{ t('common.cancel') }}</button></form>
          </section>

          <section class="settings-card backup-card wide-card">
            <header><span><ArchiveBox :size="22" /></span><div><h2>{{ t('settings.backup') }}</h2><p>{{ t('settings.backupText') }}</p></div></header>
            <div class="settings-fields backup-fields">
              <label>{{ t('settings.backupDirectory') }}<input v-model="backupConfig.directory" /></label>
              <label>{{ t('settings.dailyTime') }}<input v-model="backupConfig.daily_time" type="time" /></label>
              <label class="toggle-field">{{ t('settings.autoBackup') }}<input v-model="backupConfig.enabled" type="checkbox" /></label>
              <span class="backup-last"><small>{{ t('settings.lastBackup') }}</small><strong>{{ formatDate(backupConfig.last_backup_at) }} · {{ backupConfig.last_status }}</strong></span>
            </div>
            <div class="settings-actions"><button class="secondary" @click="persistBackup">{{ t('common.save') }}</button><button class="primary" :disabled="backupRunning" @click="triggerBackup"><Play :size="17" />{{ backupRunning ? t('common.loading') : t('settings.runNow') }}</button></div>
          </section>

          <section class="settings-card preferences-card">
            <header><span><Sun :size="22" /></span><div><h2>{{ t('settings.preferences') }}</h2><p>{{ t('settings.preferencesText') }}</p></div></header>
            <div class="settings-fields">
              <label>{{ t('settings.theme') }}<select v-model="preferences.theme"><option value="light">{{ t('settings.light') }}</option><option value="dark" disabled>{{ t('settings.darkReserved') }}</option></select></label>
              <label>{{ t('settings.defaultHome') }}<select v-model="preferences.default_home"><option value="photos">{{ t('nav.photos') }}</option><option value="timeline">{{ t('nav.timeline') }}</option><option value="recent">{{ t('nav.recent') }}</option><option value="dashboard">{{ t('nav.dashboard') }}</option></select></label>
              <label>{{ t('settings.defaultUpload') }}<select v-model="preferences.default_upload_directory"><option>Photos</option><option>Videos</option><option>Documents</option><option>Downloads</option><option>Backup</option></select></label>
              <label>{{ t('settings.photoSort') }}<select v-model="preferences.photo_sort"><option value="newest">{{ t('settings.newestTaken') }}</option><option value="oldest">{{ t('settings.oldestTaken') }}</option><option value="name">{{ t('files.name') }}</option></select></label>
            </div>
            <button class="primary" @click="persistPreferences">{{ t('common.save') }}</button>
          </section>

          <section class="settings-card system-card">
            <header><span><Database :size="22" /></span><div><h2>{{ t('settings.system') }}</h2><p>{{ t('settings.systemText') }}</p></div></header>
            <div v-if="systemInfo" class="system-grid">
              <span><small>{{ t('settings.python') }}</small><strong>{{ systemInfo.python_version }}</strong></span><span><small>{{ t('settings.sqlite') }}</small><strong>{{ systemInfo.sqlite_version }}</strong></span><span><small>{{ t('settings.version') }}</small><strong>{{ systemInfo.mynas_version }}</strong></span><span><small>{{ t('settings.databaseSize') }}</small><strong>{{ systemInfo.database_size_label }}</strong></span><span><small>{{ t('settings.thumbnailSize') }}</small><strong>{{ systemInfo.thumbnail_cache_size_label }}</strong></span><span><small>{{ t('settings.assetCount') }}</small><strong>{{ systemInfo.asset_count }}</strong></span><span><small>{{ t('settings.photoCount') }}</small><strong>{{ systemInfo.photo_count }}</strong></span><span><small>{{ t('settings.storageUsage') }}</small><strong>{{ systemInfo.storage_usage.percent }}%</strong></span>
            </div>
          </section>
        </div>
      </template>

      <template v-else>
        <section class="file-toolbar"><div class="breadcrumbs"><template v-for="(part, i) in folderBreadcrumbs" :key="part.id"><CaretRight v-if="i" :size="15" /><button :disabled="isTrash" @click="goBreadcrumb(i)">{{ part.filename }}</button></template></div><div v-if="isTrash"><button class="secondary danger" :disabled="!items.length" @click="clearTrash"><Trash :size="18" /> {{ t('trash.clear') }}</button></div><div v-else><button class="secondary" @click="showNewFolder = true"><FolderPlus :size="18" /> {{ t('files.newFolder') }}</button><button class="primary" @click="showUpload = true"><UploadSimple :size="18" /> {{ t('files.upload') }}</button></div></section>
        <section class="files-panel">
          <div class="file-head"><span>{{ t('files.name') }}</span><span>{{ t('files.size') }}</span><span>{{ t('files.modified') }}</span><span></span></div>
          <div v-if="loading" class="empty-state"><ArrowClockwise class="spin" :size="32" /><strong>{{ t('files.reading') }}</strong></div>
          <div v-else-if="!filteredItems.length" class="empty-state"><Trash v-if="isTrash" :size="48" weight="duotone" /><Folder v-else :size="48" weight="duotone" /><strong>{{ isTrash ? t('trash.empty') : t('files.empty') }}</strong><p>{{ isTrash ? t('trash.emptyText') : t('files.emptyText') }}</p><button v-if="!isTrash" class="primary" @click="showUpload = true"><UploadSimple :size="18" /> {{ t('files.uploadFile') }}</button></div>
          <div v-else-if="current === 'Photos'" class="photo-grid"><article v-for="item in filteredItems" :key="item.id" class="photo-card" @dblclick="openItem(item)"><button class="photo-preview" @click="openItem(item)"><img v-if="item.mime_type?.startsWith('image/')" :src="item.thumbnail_url || assetDownloadUrl(item.id)" :alt="item.name" loading="lazy" @error="$event.target.style.display='none'" /><span v-else><Folder v-if="item.is_directory" :size="44" weight="duotone" /><Image v-else :size="44" weight="duotone" /></span></button><div><span><strong>{{ item.name }}</strong><small>{{ item.size_label }} · {{ formatDate(item.modified_at) }}</small></span><button :title="t('common.delete')" @click="remove(item)"><Trash :size="17" /></button></div></article></div>
          <div v-else v-for="item in filteredItems" :key="item.id" class="file-row" @dblclick="!isTrash && openItem(item)"><button class="file-name" :disabled="isTrash" @click="!isTrash && openItem(item)"><span :class="['file-icon', { folder: item.is_directory }]"><Folder v-if="item.is_directory" :size="24" weight="fill" /><File v-else :size="24" weight="duotone" /></span><span>{{ item.name }}</span></button><span>{{ item.size_label }}</span><span>{{ formatDate(isTrash ? item.deleted_at : item.modified_at) }}</span><span class="row-actions"><template v-if="isTrash"><button :title="t('trash.restore')" @click="restoreItem(item)"><ArrowClockwise :size="18" /></button><button :title="t('trash.permanent')" class="danger-action" @click="permanentlyRemove(item)"><Trash :size="18" /></button></template><template v-else><a v-if="!item.is_directory" :href="assetDownloadUrl(item.id)" :title="t('nav.downloads')"><DownloadSimple :size="18" /></a><button :title="t('common.delete')" @click="remove(item)"><Trash :size="18" /></button></template></span></div>
        </section>
      </template>
    </main>

    <div v-if="lightboxPhoto" class="photo-lightbox" role="dialog" aria-modal="true" :aria-label="lightboxPhoto.name" @click.self="closeLightbox">
      <div class="lightbox-top"><div><strong>{{ lightboxPhoto.name }}</strong><span>{{ formatPhotoDay(lightboxPhoto.taken_at) }} · {{ lightboxIndex + 1 }} / {{ photoItems.length }}</span></div><button :class="{ active: lightboxPhoto.is_favorite }" :title="lightboxPhoto.is_favorite ? t('photos.unfavorite') : t('photos.favorite')" @click="toggleFavorite(lightboxPhoto)"><Heart :size="21" :weight="lightboxPhoto.is_favorite ? 'fill' : 'bold'" /></button><button :title="t('photos.closeEsc')" @click="closeLightbox"><X :size="22" /></button></div>
      <button class="lightbox-arrow previous" :title="t('photos.previous')" @click="stepLightbox(-1)"><ArrowLeft :size="26" /></button>
      <img :src="assetDownloadUrl(lightboxPhoto.id)" :alt="lightboxPhoto.name" loading="lazy" />
      <button class="lightbox-arrow next" :title="t('photos.next')" @click="stepLightbox(1)"><ArrowRight :size="26" /></button>
    </div>

    <div v-if="showUpload" class="modal-backdrop" @click.self="showUpload = false"><div class="modal"><button class="modal-close" @click="showUpload = false"><X :size="20" /></button><span class="modal-icon"><CloudArrowUp :size="30" /></span><h2>{{ t('upload.title', { target: (isDashboard || isPhotoView) ? t('dashboard.photos') : t(meta[current]?.labelKey) }) }}</h2><p>{{ t('upload.safeText') }}</p><label class="dropzone"><input type="file" multiple accept="image/jpeg,image/png,video/mp4,application/pdf" @change="chooseFiles" /><UploadSimple :size="28" /><strong>{{ selectedFiles.length ? t('upload.chosen', { count: selectedFiles.length }) : t('upload.drop') }}</strong><span>{{ t('upload.blocked') }}</span></label><div v-if="uploadProgress" class="progress"><i :style="{ width: uploadProgress + '%' }"></i></div><button class="primary wide" :disabled="!selectedFiles.length" @click="submitUpload">{{ t('upload.start') }}</button></div></div>
    <div v-if="showNewFolder" class="modal-backdrop" @click.self="showNewFolder = false"><div class="modal small"><button class="modal-close" @click="showNewFolder = false"><X :size="20" /></button><span class="modal-icon"><FolderPlus :size="28" /></span><h2>{{ t('files.newFolder') }}</h2><p>{{ t('files.createText') }}</p><input v-model="folderName" class="text-input" :placeholder="t('files.folderName')" @keyup.enter="submitFolder" /><button class="primary wide" :disabled="!folderName.trim()" @click="submitFolder">{{ t('files.createFolder') }}</button></div></div>
    <div v-if="dragActive" class="drag-overlay"><CloudArrowUp :size="44" /><strong>{{ t('upload.drop') }}</strong></div>
    <div v-if="toast" :class="['toast', toast.type]">{{ toast.message }}</div>
  </div>
</template>
