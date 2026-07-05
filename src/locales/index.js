import { ref } from 'vue'
import zh from './zh.ts'
import en from './en.ts'

const dictionaries = { zh, en }
export const locale = ref(localStorage.getItem('mynas-locale') || 'zh')

export function setLocale(value) {
  locale.value = dictionaries[value] ? value : 'zh'
  localStorage.setItem('mynas-locale', locale.value)
  document.documentElement.lang = locale.value === 'zh' ? 'zh-CN' : 'en'
}

export function t(key, variables = {}) {
  const value = key.split('.').reduce((current, part) => current?.[part], dictionaries[locale.value]) ?? key
  return Object.entries(variables).reduce((text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)), value)
}

setLocale(locale.value)
