import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000
})

export const ocrRecognize = (file, languages = null) => {
  const formData = new FormData()
  formData.append('file', file)
  if (languages) {
    formData.append('languages', languages)
  }
  return api.post('/ocr', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export const uiCheck = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/ui-check', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000 // 5 分钟：多 Agent 串行检测耗时较长
  })
}

export const uiCheckBatch = (files, concurrency = 2) => {
  const formData = new FormData()
  ;(files || []).forEach(f => formData.append('files', f))
  formData.append('concurrency', String(concurrency))
  return api.post('/ui-check-batch', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000
  })
}

export const fullAnalyze = (file, languages = null) => {
  const formData = new FormData()
  formData.append('file', file)
  if (languages) {
    formData.append('languages', languages)
  }
  return api.post('/analyze', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000 // 5 分钟：包含 OCR + UI 多 Agent
  })
}

export const healthCheck = () => api.get('/health')

/**
 * Leader Agent 训练：上传「有问题」「没问题」两类图片
 * @param {File[]} problemFiles - 有问题的图片
 * @param {File[]} noProblemFiles - 无问题的图片
 * @param {number} maxRounds - 每张图最多重试次数
 * @param {number} sampleSize - 每类抽样数量，0 表示全部
 * @param {number} requestDelay - 每次调用上游 API 后等待秒数，避免 429 限流；0 表示不等待
 */
export const leaderTrain = (problemFiles, noProblemFiles, maxRounds = 3, sampleSize = 10, requestDelay = 2) => {
  const formData = new FormData()
  ;(problemFiles || []).forEach(f => formData.append('problem', f))
  ;(noProblemFiles || []).forEach(f => formData.append('no_problem', f))
  formData.append('max_rounds', String(maxRounds))
  formData.append('sample_size', String(sampleSize))
  formData.append('request_delay', String(requestDelay))
  return api.post('/leader-train', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 1800000  // 30 分钟，避免请求间隔较大时超时
  })
}

/** 数据管理：训练记录列表 */
export const getTrainingRuns = (limit = 50) => api.get('/training-runs', { params: { limit } })

/** 数据管理：单次训练详情 */
export const getTrainingRun = (runId) => api.get(`/training-runs/${runId}`)

/** 数据管理：提示词版本列表（RAG 知识库） */
export const getPromptVersions = (limit = 50) => api.get('/prompt-versions', { params: { limit } })

// --------------- 测试报告 ---------------

export const createTestReport = (total = 0) => {
  const formData = new FormData()
  formData.append('total', String(total))
  return api.post('/test-reports', formData)
}

export const addTestReportItem = (reportId, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/test-reports/${reportId}/items`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000
  })
}

export const completeTestReport = (reportId) => api.patch(`/test-reports/${reportId}/complete`)

export const getTestReports = (limit = 50) => api.get('/test-reports', { params: { limit } })

export const getTestReport = (reportId) => api.get(`/test-reports/${reportId}`)

export const getReportImageUrl = (reportId, filename) =>
  `/api/report-images/${reportId}/${encodeURIComponent(filename)}`
