<template>
  <div class="app-container">
    <!-- 头部 -->
    <header class="header">
      <div class="logo">
        <span class="logo-icon">🔍</span>
        <h1>多语言 OCR Agent</h1>
      </div>
      <p class="subtitle">图片文字识别与 UI 显示检测</p>
    </header>

    <!-- 主内容 -->
    <main class="main-content">
      <el-tabs v-model="activeTab" class="main-tabs">
        <el-tab-pane label="📷 图片检测" name="detect">
      <!-- 上传区域 -->
      <el-card class="upload-card">
        <template #header>
          <div class="card-header">
            <span>📤 上传图片</span>
          </div>
        </template>
        
        <el-upload
          class="upload-area"
          drag
          multiple
          :auto-upload="false"
          :file-list="detectFileList"
          accept="image/*"
          :on-change="handleDetectFileChange"
          :on-remove="handleDetectFileRemove"
        >
          <div v-if="!previewUrl" class="upload-placeholder">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">将图片拖到此处，或点击上传</div>
            <div class="upload-hint">支持 PNG、JPG、JPEG、GIF 格式 | 支持多图批量检测 | 也可以直接粘贴图片（Ctrl+V / Cmd+V）</div>
          </div>
          <img v-else :src="previewUrl" class="preview-image" />
        </el-upload>
        <div class="detect-upload-actions">
          <input
            ref="detectFolderInput"
            type="file"
            webkitdirectory
            directory
            multiple
            accept="image/*"
            class="leader-folder-input"
            @change="handleDetectFolderChange"
          />
          <el-button size="small" @click="triggerDetectFolderPick">
            📁 上传图片文件夹
          </el-button>
        </div>

        <!-- 语言选择 -->
        <div class="language-select" v-if="previewUrl">
          <el-select
            v-model="selectedLanguages"
            multiple
            placeholder="选择期望识别的语言（可选）"
            style="width: 100%"
          >
            <el-option label="中文" value="中文" />
            <el-option label="英文" value="英文" />
            <el-option label="日文" value="日文" />
            <el-option label="韩文" value="韩文" />
            <el-option label="法文" value="法文" />
            <el-option label="德文" value="德文" />
            <el-option label="西班牙文" value="西班牙文" />
            <el-option label="俄文" value="俄文" />
          </el-select>
        </div>

        <!-- 操作按钮 -->
        <div class="action-buttons" v-if="previewUrl">
          <el-button type="primary" @click="handleOCR" :loading="loading.ocr">
            📝 文字识别
          </el-button>
          <el-button type="warning" @click="handleUICheck" :loading="loading.uiCheck">
            🔎 UI 检测
          </el-button>
          <el-button
            type="warning"
            plain
            @click="handleBatchUICheck"
            :loading="loading.batchUiCheck"
            :disabled="detectFiles.length === 0 || loading.uiCheck || loading.full"
          >
            🧪 批量 UI 检测（并发）
          </el-button>
          <el-button type="success" @click="handleFullAnalyze" :loading="loading.full">
            ✨ 综合分析
          </el-button>
          <el-button @click="clearAll">清空</el-button>
        </div>
        <div class="batch-summary" v-if="detectFiles.length > 1">
          已加入检测队列 {{ detectFiles.length }} 张
          <label class="batch-concurrency-option">
            并发数：
            <el-input-number v-model="batchConcurrency" :min="1" :max="5" size="small" />
          </label>
        </div>
        <div class="ui-progress-panel" v-if="uiProgress.active">
          <div class="ui-progress-title">
            {{ uiProgress.mode === 'full' ? '综合分析进行中' : 'UI 检测进行中' }}
          </div>
          <div class="ui-progress-current">当前阶段：{{ uiProgress.stepText }}</div>
          <div class="ui-progress-meta">已等待 {{ uiProgress.elapsedSeconds }}s（多 Agent 串行处理中）</div>
          <div class="ui-progress-steps">
            <span
              v-for="(step, idx) in uiProgress.phases"
              :key="`${step}-${idx}`"
              class="ui-progress-step"
              :class="{ 'ui-progress-step-active': idx === uiProgress.stepIndex }"
            >
              {{ idx + 1 }}. {{ step }}
            </span>
          </div>
        </div>
        <div class="batch-progress-panel" v-if="loading.batchUiCheck">
          批量检测进行中（并发 {{ batchConcurrency }}）：{{ detectFiles.length }} 张图片
          <span class="batch-timer">· 已用时 {{ batchTimer.elapsedSec }}s</span>
          <span class="batch-done-count" v-if="batchUiResults.length">
            · 已完成 {{ batchUiResults.filter(r => r.status === 'done').length }}/{{ batchUiResults.length }}
          </span>
        </div>
      </el-card>

      <el-card class="result-card" v-if="batchUiResults.length">
        <template #header>
          <div class="card-header">
            <span>📚 批量 UI 检测结果</span>
            <span class="batch-header-meta">
              <el-tag size="small">共 {{ batchUiResults.length }} 张</el-tag>
              <span v-if="batchFinalElapsed" class="batch-elapsed-tag">耗时 {{ batchFinalElapsed }}s</span>
            </span>
          </div>
        </template>
        <el-table :data="batchUiResults" size="small" stripe max-height="400">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="filename" label="图片" min-width="140" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'pending'" type="info" size="small">等待中</el-tag>
              <el-tag v-else-if="row.status === 'running'" type="primary" size="small">
                <span class="status-running-dot"></span> 检测中
              </el-tag>
              <el-tag v-else :type="row.success ? 'success' : 'danger'" size="small">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="是否有问题" width="100">
            <template #default="{ row }">
              <span v-if="row.status !== 'done'">—</span>
              <span v-else-if="!row.success">—</span>
              <el-tag v-else :type="row.result?.has_issues ? 'warning' : 'success'" size="small">
                {{ row.result?.has_issues ? '有问题' : '无问题' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="得分" width="80">
            <template #default="{ row }">
              <span v-if="row.status !== 'done' || !row.success">—</span>
              <span v-else :class="{ 'score-low': (row.result?.score ?? 100) < 80 }">{{ row.result?.score ?? 0 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="问题类型" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.status !== 'done' || !row.success">—</span>
              <span v-else>{{ getIssueTypesText(row.result?.issues) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row, $index }">
              <el-button
                v-if="row.status === 'done'"
                type="primary" link size="small"
                @click="openBatchImageViewer($index)"
              >查看</el-button>
              <span v-else class="op-placeholder">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 结果区域 -->
      <div class="results-area" v-if="ocrResult || uiResult">
        <!-- OCR 结果 -->
        <el-card class="result-card" v-if="ocrResult">
          <template #header>
            <div class="card-header">
              <span>📝 文字识别结果</span>
              <el-tag :type="ocrResult.success ? 'success' : 'danger'" size="small">
                {{ ocrResult.success ? '成功' : '失败' }}
              </el-tag>
            </div>
          </template>
          
          <div v-if="ocrResult.success">
            <!-- 检测到的语言 -->
            <div class="result-section" v-if="ocrResult.languages_detected?.length">
              <h4>检测到的语言</h4>
              <div class="language-tags">
                <el-tag v-for="lang in ocrResult.languages_detected" :key="lang" class="lang-tag">
                  {{ lang }}
                </el-tag>
              </div>
            </div>
            
            <!-- 识别文字 -->
            <div class="result-section">
              <h4>识别内容</h4>
              <div class="text-content">{{ ocrResult.text }}</div>
            </div>
            
            <!-- 文字块详情 -->
            <div class="result-section" v-if="ocrResult.text_blocks?.length">
              <h4>文字块详情</h4>
              <el-table :data="ocrResult.text_blocks" size="small">
                <el-table-column prop="content" label="内容" />
                <el-table-column prop="language" label="语言" width="80" />
                <el-table-column prop="position" label="位置" width="100" />
              </el-table>
            </div>
          </div>
          <div v-else class="error-message">{{ ocrResult.message }}</div>
        </el-card>

        <!-- UI 检测结果 -->
        <el-card class="result-card" v-if="uiResult">
          <template #header>
            <div class="card-header">
              <span>🔎 UI 检测结果</span>
              <el-tag :type="getScoreType(uiResult.score)" size="small">
                得分: {{ uiResult.score }}
              </el-tag>
            </div>
          </template>
          
          <div v-if="uiResult.success">
            <!-- 问题状态 -->
            <el-alert
              :title="getUIStatusTitle(uiResult)"
              :type="getUIStatusType(uiResult)"
              :closable="false"
              show-icon
            />
            
            <!-- AI 对 UI 结构的整体判断 -->
            <div class="result-section" v-if="uiResult.structure_assessment">
              <h4>AI 对 UI 结构的判断</h4>
              <div class="structure-assessment" :class="{ 'structure-ok': uiResult.structure_ok !== false, 'structure-ng': uiResult.structure_ok === false }">
                <el-tag v-if="uiResult.structure_ok !== false" type="success" size="small">结构正常</el-tag>
                <el-tag v-else type="warning" size="small">结构异常</el-tag>
                <span class="structure-text">{{ uiResult.structure_assessment }}</span>
              </div>
            </div>

            <!-- 专项 Agent 过程可视化 -->
            <div class="result-section" v-if="uiResult.agent_process?.length">
              <h4>专项 Agent 过程可视化</h4>
              <div class="agent-process-list">
                <div
                  v-for="(step, idx) in uiResult.agent_process"
                  :key="`${step.issue_type}-${idx}`"
                  class="agent-process-item"
                  :class="{ 'agent-process-hit': step.has_issue, 'agent-process-pass': !step.has_issue }"
                >
                  <div class="agent-process-head">
                    <span class="agent-step-index">Step {{ idx + 1 }}</span>
                    <span class="agent-name">{{ step.agent }}</span>
                    <el-tag :type="step.has_issue ? 'warning' : 'success'" size="small">
                      {{ step.has_issue ? '发现问题' : '未发现问题' }}
                    </el-tag>
                  </div>
                  <div class="agent-issue-type">
                    类型：{{ step.issue_type }}
                    <span v-if="step.model_elapsed_ms" class="agent-timing">耗时 {{ (step.model_elapsed_ms / 1000).toFixed(1) }}s</span>
                    <span v-if="step.rounds > 1" class="agent-timing">{{ step.rounds }} 轮</span>
                  </div>
                  <div class="agent-reason">{{ step.reason }}</div>
                </div>
              </div>
            </div>
            
            <!-- 问题列表 -->
            <div class="result-section" v-if="uiResult.issues?.length">
              <h4>问题详情</h4>
              <div class="issues-list">
                <div v-for="(issue, index) in uiResult.issues" :key="index" class="issue-item">
                  <div class="issue-header">
                    <el-tag :type="getSeverityType(issue.severity)" size="small">
                      {{ issue.severity }}
                    </el-tag>
                    <span class="issue-type">{{ issue.type }}</span>
                  </div>
                  <div class="issue-desc">{{ issue.description }}</div>
                  <div class="issue-location">📍 {{ issue.location }}</div>
                  <div class="issue-suggestion">💡 {{ issue.suggestion }}</div>
                </div>
              </div>
            </div>
            
            <!-- 总结 -->
            <div class="result-section" v-if="uiResult.summary">
              <h4>总结</h4>
              <div class="summary-content">{{ uiResult.summary }}</div>
            </div>

            <!-- 耗时 -->
            <div class="result-section" v-if="uiResult.wall_elapsed_ms">
              <div class="timing-info">
                实际耗时 {{ (uiResult.wall_elapsed_ms / 1000).toFixed(1) }}s
                <span v-if="uiResult.elapsed_ms">· 模型总耗时 {{ (uiResult.elapsed_ms / 1000).toFixed(1) }}s</span>
              </div>
            </div>
          </div>
          <div v-else class="error-message">{{ uiResult.message }}</div>
        </el-card>
      </div>
        </el-tab-pane>

        <!-- 测试报告 -->
        <el-tab-pane label="📋 测试报告" name="reports">
          <el-card class="report-list-card">
            <template #header>
              <div class="card-header">
                <span>📋 历史测试报告</span>
                <el-button type="primary" size="small" @click="loadTestReports">刷新</el-button>
              </div>
            </template>
            <el-table :data="testReports" stripe size="small" max-height="500" v-if="testReports.length">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="created_at" label="创建时间" width="180" />
              <el-table-column prop="total" label="总数" width="70" />
              <el-table-column label="成功" width="70">
                <template #default="{ row }">
                  <span class="stat-ok">{{ row.success_count || 0 }}</span>
                </template>
              </el-table-column>
              <el-table-column label="有问题" width="80">
                <template #default="{ row }">
                  <span :class="{ 'stat-warn': row.has_issue_count > 0 }">{{ row.has_issue_count || 0 }}</span>
                </template>
              </el-table-column>
              <el-table-column label="无问题" width="80">
                <template #default="{ row }">{{ row.no_issue_count || 0 }}</template>
              </el-table-column>
              <el-table-column label="失败" width="70">
                <template #default="{ row }">
                  <span :class="{ 'stat-fail': row.fail_count > 0 }">{{ row.fail_count || 0 }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'completed' ? 'success' : 'warning'" size="small">
                    {{ row.status === 'completed' ? '已完成' : '进行中' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" link size="small" @click="openTestReportDetail(row.id)">查看详情</el-button>
                </template>
              </el-table-column>
            </el-table>
            <p v-else class="data-empty">暂无测试报告，请先进行批量 UI 检测</p>
          </el-card>

          <!-- 报告详情弹窗 -->
          <el-dialog
            v-model="showReportDetailDialog"
            title="测试报告详情"
            width="92%"
            top="2vh"
            class="report-detail-dialog"
            destroy-on-close
            @closed="selectedReport = null"
          >
            <template v-if="selectedReport" #default>
              <!-- 汇总卡片 -->
              <section class="rpt-summary">
                <div class="rpt-summary-cards">
                  <div class="rpt-card">
                    <span class="rpt-card-value">{{ selectedReport.report?.total || 0 }}</span>
                    <span class="rpt-card-label">总图片数</span>
                  </div>
                  <div class="rpt-card rpt-card-ok">
                    <span class="rpt-card-value">{{ selectedReport.report?.no_issue_count || 0 }}</span>
                    <span class="rpt-card-label">无问题</span>
                  </div>
                  <div class="rpt-card rpt-card-warn">
                    <span class="rpt-card-value">{{ selectedReport.report?.has_issue_count || 0 }}</span>
                    <span class="rpt-card-label">有问题</span>
                  </div>
                  <div class="rpt-card rpt-card-fail">
                    <span class="rpt-card-value">{{ selectedReport.report?.fail_count || 0 }}</span>
                    <span class="rpt-card-label">检测失败</span>
                  </div>
                </div>
                <div class="rpt-time-info" v-if="selectedReport.report?.wall_elapsed_ms">
                  耗时 {{ (selectedReport.report.wall_elapsed_ms / 1000).toFixed(1) }}s ·
                  创建于 {{ selectedReport.report.created_at }}
                </div>
              </section>

              <!-- 筛选栏 -->
              <section class="rpt-filters">
                <label class="rpt-filter-item">
                  状态：
                  <el-select v-model="reportFilterStatus" size="small" style="width: 130px">
                    <el-option label="全部" value="all" />
                    <el-option label="有问题" value="has_issues" />
                    <el-option label="无问题" value="no_issues" />
                    <el-option label="检测失败" value="failed" />
                  </el-select>
                </label>
                <label class="rpt-filter-item">
                  问题类型：
                  <el-select v-model="reportFilterIssueType" size="small" style="width: 160px">
                    <el-option
                      v-for="opt in ISSUE_TYPE_OPTIONS"
                      :key="opt.value"
                      :label="opt.label"
                      :value="opt.value"
                    />
                  </el-select>
                </label>
                <span class="rpt-filter-count">
                  显示 {{ filteredReportItems().length }} / {{ selectedReport.items?.length || 0 }} 条
                </span>
              </section>

              <!-- 明细表格 -->
              <section class="rpt-table-section">
                <el-table :data="filteredReportItems()" stripe size="small" max-height="55vh">
                  <el-table-column type="index" label="#" width="50" />
                  <el-table-column prop="filename" label="图片" min-width="140" show-overflow-tooltip />
                  <el-table-column label="状态" width="90">
                    <template #default="{ row }">
                      <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                        {{ row.success ? '成功' : '失败' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="有无问题" width="100">
                    <template #default="{ row }">
                      <span v-if="!row.success">—</span>
                      <el-tag v-else :type="row.has_issues ? 'warning' : 'success'" size="small">
                        {{ row.has_issues ? '有问题' : '无问题' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="得分" width="70">
                    <template #default="{ row }">
                      <span v-if="!row.success">—</span>
                      <span v-else :class="{ 'score-low': (row.score ?? 100) < 80 }">{{ row.score ?? 0 }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="问题类型" min-width="130" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ getIssueTypesText(row.issues) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="摘要" min-width="160" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ row.success ? (row.summary || '—') : row.message }}
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="80" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" link size="small" @click="openImageViewer(row, selectedReport.report.id)">查看</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
            </template>
          </el-dialog>
        </el-tab-pane>

        <!-- Leader Agent 入口（暂时隐藏） -->
        <el-tab-pane v-if="false" label="🎯 Leader Agent" name="leader">
          <el-card class="leader-card">
            <template #header>
              <div class="card-header">
                <span>🎯 Leader Agent 训练</span>
                <span class="card-desc">上传「有问题」「没问题」两类图片，自动优化 Language Agent 的检测提示词</span>
              </div>
            </template>

            <div class="leader-upload-row">
              <div class="leader-upload-box">
                <div class="leader-upload-label">有问题的图片</div>
                <div class="leader-upload-actions">
                  <input
                    ref="problemFolderInput"
                    type="file"
                    webkitdirectory
                    directory
                    multiple
                    accept="image/*"
                    class="leader-folder-input"
                    @change="(e) => handleLeaderFolderChange(e, 'problem')"
                  />
                  <el-button size="small" @click="triggerFolderPick('problem')">
                    📁 选择文件夹
                  </el-button>
                  <span class="leader-upload-divider">或</span>
                  <el-upload
                    class="leader-upload-inline"
                    multiple
                    accept="image/*"
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(f) => handleLeaderFileChange(f, 'problem')"
                  >
                    <el-button size="small" plain>多选图片</el-button>
                  </el-upload>
                </div>
                <el-upload
                  class="leader-upload"
                  drag
                  multiple
                  accept="image/*"
                  :auto-upload="false"
                  :file-list="problemFileList"
                  :on-change="(f) => handleLeaderFileChange(f, 'problem')"
                  :on-remove="(f) => handleLeaderFileRemove(f, 'problem')"
                >
                  <el-icon class="leader-upload-icon"><UploadFilled /></el-icon>
                  <div class="leader-upload-text">点击或拖拽多张图片到此处</div>
                  <div class="leader-upload-hint">支持 jpg / png / gif / webp · 也可用上方「选择文件夹」</div>
                </el-upload>
                <div class="leader-file-count">已选 {{ problemFiles.length }} 张</div>
              </div>
              <div class="leader-upload-box">
                <div class="leader-upload-label">无问题的图片</div>
                <div class="leader-upload-actions">
                  <input
                    ref="noProblemFolderInput"
                    type="file"
                    webkitdirectory
                    directory
                    multiple
                    accept="image/*"
                    class="leader-folder-input"
                    @change="(e) => handleLeaderFolderChange(e, 'no_problem')"
                  />
                  <el-button size="small" @click="triggerFolderPick('no_problem')">
                    📁 选择文件夹
                  </el-button>
                  <span class="leader-upload-divider">或</span>
                  <el-upload
                    class="leader-upload-inline"
                    multiple
                    accept="image/*"
                    :auto-upload="false"
                    :show-file-list="false"
                    :on-change="(f) => handleLeaderFileChange(f, 'no_problem')"
                  >
                    <el-button size="small" plain>多选图片</el-button>
                  </el-upload>
                </div>
                <el-upload
                  class="leader-upload"
                  drag
                  multiple
                  accept="image/*"
                  :auto-upload="false"
                  :file-list="noProblemFileList"
                  :on-change="(f) => handleLeaderFileChange(f, 'no_problem')"
                  :on-remove="(f) => handleLeaderFileRemove(f, 'no_problem')"
                >
                  <el-icon class="leader-upload-icon"><UploadFilled /></el-icon>
                  <div class="leader-upload-text">点击或拖拽多张图片到此处</div>
                  <div class="leader-upload-hint">支持 jpg / png / gif / webp · 也可用上方「选择文件夹」</div>
                </el-upload>
                <div class="leader-file-count">已选 {{ noProblemFiles.length }} 张</div>
              </div>
            </div>

            <div class="leader-options">
              <label class="leader-option">
                <span>每张图最多重试次数</span>
                <el-input-number v-model="leaderOptions.maxRounds" :min="1" :max="10" size="small" />
              </label>
              <label class="leader-option">
                <span>每类抽样数量（0=全部）</span>
                <el-input-number v-model="leaderOptions.sampleSize" :min="0" :max="200" size="small" />
              </label>
              <label class="leader-option">
                <span>请求间隔（秒，防 429）</span>
                <el-input-number v-model="leaderOptions.requestDelay" :min="0" :max="30" :step="0.5" size="small" />
              </label>
            </div>

            <div class="leader-actions">
              <el-button
                type="primary"
                size="large"
                :loading="loading.leader"
                :disabled="!(problemFiles.length || noProblemFiles.length)"
                @click="handleLeaderTrain"
              >
                🚀 开始训练
              </el-button>
              <el-button @click="clearLeaderFiles">清空文件</el-button>
              <p class="leader-timeout-hint">请求间隔较大或图片较多时，训练可能需 10–30 分钟，请勿关闭页面。</p>
            </div>

            <div v-if="leaderResult" ref="leaderResultRef" class="leader-result">
              <h3 class="leader-result-heading">📋 测试结果</h3>
              <el-alert
                :title="leaderResult.message"
                :type="leaderResult.success ? 'success' : (leaderResult.total > 0 ? 'warning' : 'error')"
                show-icon
                :closable="false"
              />
              <div class="leader-stats">
                <el-tag>共 {{ leaderResult.total ?? 0 }} 张</el-tag>
                <el-tag type="success">通过 {{ leaderResult.ok ?? 0 }} 张</el-tag>
                <el-tag type="danger">失败 {{ leaderResult.failed ?? Math.max(0, (leaderResult.total ?? 0) - (leaderResult.ok ?? 0)) }} 张</el-tag>
                <el-tag type="warning">提示词修改 {{ leaderResult.updated_prompt_count ?? 0 }} 次</el-tag>
                <el-button type="primary" class="leader-report-btn" @click="openReportDialog">
                  📄 测试报告
                </el-button>
              </div>
              <div v-if="leaderResult.details?.length" class="leader-details-section">
                <h4 class="leader-details-title">每张图片执行结果</h4>
                <el-table :data="leaderResult.details" stripe size="small" class="leader-details-table" max-height="400">
                  <el-table-column prop="filename" label="图片" width="140" show-overflow-tooltip />
                  <el-table-column prop="source_label" label="来源" width="90" />
                  <el-table-column label="预期" width="70">
                    <template #default="{ row }">{{ row.expected_has_issues ? '有问题' : '无问题' }}</template>
                  </el-table-column>
                  <el-table-column label="实际" width="70">
                    <template #default="{ row }">
                      <span v-if="row.actual_has_issues === null">—</span>
                      <span v-else>{{ row.actual_has_issues ? '有问题' : '无问题' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="结果" width="80">
                    <template #default="{ row }">
                      <el-tag :type="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '通过' : '失败' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="attempt_count" label="调用次数" width="90" />
                  <el-table-column prop="retry_count" label="重试次数" width="90" />
                  <el-table-column prop="message" label="备注" min-width="120" show-overflow-tooltip />
                </el-table>
              </div>
              <el-collapse v-if="leaderResult.final_prompt" class="leader-prompt-collapse">
                <el-collapse-item title="查看优化后的提示词" name="prompt">
                  <pre class="leader-final-prompt">{{ leaderResult.final_prompt }}</pre>
                </el-collapse-item>
              </el-collapse>
            </div>

            <!-- 测试报告弹窗（独立报告页） -->
            <el-dialog
              v-model="showReportDialog"
              title="Leader Agent 测试报告"
              width="90%"
              top="3vh"
              class="report-dialog"
              destroy-on-close
              @closed="showReportDialog = false"
            >
              <template #header>
                <span class="report-dialog-title">📄 Leader Agent 测试报告</span>
              </template>
              <div v-if="leaderResult" class="report-page">
                <section class="report-summary">
                  <h4>汇总</h4>
                  <div class="report-summary-cards">
                    <div class="report-card">
                      <span class="report-card-value">{{ leaderResult.total ?? 0 }}</span>
                      <span class="report-card-label">总图片数</span>
                    </div>
                    <div class="report-card report-card-ok">
                      <span class="report-card-value">{{ leaderResult.ok ?? 0 }}</span>
                      <span class="report-card-label">通过</span>
                    </div>
                    <div class="report-card report-card-fail">
                      <span class="report-card-value">{{ leaderResult.failed ?? Math.max(0, (leaderResult.total ?? 0) - (leaderResult.ok ?? 0)) }}</span>
                      <span class="report-card-label">失败</span>
                    </div>
                    <div class="report-card report-card-warn">
                      <span class="report-card-value">{{ leaderResult.updated_prompt_count ?? 0 }}</span>
                      <span class="report-card-label">提示词修改次数</span>
                    </div>
                  </div>
                  <p class="report-message">{{ leaderResult.message }}</p>
                </section>
                <section class="report-details">
                  <h4>每张图片执行结果</h4>
                  <el-table
                    v-if="leaderResult.details?.length"
                    :data="leaderResult.details"
                    stripe
                    size="small"
                    class="report-table"
                    max-height="50vh"
                  >
                    <el-table-column type="index" label="序号" width="60" />
                    <el-table-column prop="filename" label="图片" min-width="120" show-overflow-tooltip />
                    <el-table-column prop="source_label" label="来源" width="90" />
                    <el-table-column label="预期" width="80">
                      <template #default="{ row }">{{ row.expected_has_issues ? '有问题' : '无问题' }}</template>
                    </el-table-column>
                    <el-table-column label="实际" width="80">
                      <template #default="{ row }">
                        <span v-if="row.actual_has_issues === null">—</span>
                        <span v-else>{{ row.actual_has_issues ? '有问题' : '无问题' }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="结果" width="90">
                      <template #default="{ row }">
                        <el-tag :type="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '通过' : '失败' }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column prop="attempt_count" label="调用次数" width="100" />
                    <el-table-column prop="retry_count" label="重试次数" width="100" />
                    <el-table-column prop="message" label="备注" min-width="160" show-overflow-tooltip />
                  </el-table>
                  <p v-else class="report-no-details">暂无明细数据</p>
                </section>
                <section v-if="leaderResult.final_prompt" class="report-prompt">
                  <h4>优化后的提示词</h4>
                  <pre class="report-prompt-content">{{ leaderResult.final_prompt }}</pre>
                </section>
              </div>
            </el-dialog>
          </el-card>
        </el-tab-pane>

        <!-- 数据管理：DB / RAG 可视化（暂时隐藏） -->
        <el-tab-pane v-if="false" label="📊 数据管理" name="data">
          <el-card class="data-card">
            <template #header>
              <div class="card-header">
                <span>📊 数据管理</span>
                <span class="card-desc">训练记录与 RAG 提示词版本</span>
              </div>
            </template>
            <el-tabs v-model="dataSubTab" class="data-sub-tabs">
              <el-tab-pane label="训练记录" name="runs">
                <div class="data-toolbar">
                  <el-button type="primary" size="small" @click="loadTrainingRuns" :loading="loading.dataRuns">刷新</el-button>
                </div>
                <el-table :data="trainingRuns" stripe size="small" class="data-table" max-height="400">
                  <el-table-column prop="id" label="Run ID" width="280" show-overflow-tooltip />
                  <el-table-column prop="created_at" label="创建时间" width="180" />
                  <el-table-column prop="total" label="总数" width="70" />
                  <el-table-column prop="ok" label="通过" width="70" />
                  <el-table-column prop="failed" label="失败" width="70" />
                  <el-table-column prop="updated_prompt_count" label="提示词修改" width="100" />
                  <el-table-column label="操作" width="100" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" link size="small" @click="openRunDetail(row.id)">详情</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <p v-if="!loading.dataRuns && !trainingRuns.length" class="data-empty">暂无训练记录</p>
              </el-tab-pane>
              <el-tab-pane label="提示词版本（RAG）" name="versions">
                <div class="data-toolbar">
                  <el-button type="primary" size="small" @click="loadPromptVersions" :loading="loading.dataVersions">刷新</el-button>
                </div>
                <el-table :data="promptVersions" stripe size="small" class="data-table" max-height="400">
                  <el-table-column prop="id" label="ID" width="70" />
                  <el-table-column prop="run_id" label="Run ID" width="220" show-overflow-tooltip />
                  <el-table-column prop="created_at" label="创建时间" width="180" />
                  <el-table-column prop="detection_reason" label="检测原因" min-width="120" show-overflow-tooltip />
                  <el-table-column prop="source_label" label="来源" width="90" />
                  <el-table-column label="操作" width="100" fixed="right">
                    <template #default="{ row }">
                      <el-button type="primary" link size="small" @click="openPromptDetail(row)">详情</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <p v-if="!loading.dataVersions && !promptVersions.length" class="data-empty">暂无提示词版本</p>
              </el-tab-pane>
            </el-tabs>
          </el-card>

          <!-- 训练记录详情弹窗 -->
          <el-dialog
            v-model="showRunDetailDialog"
            title="训练记录详情"
            width="85%"
            top="4vh"
            class="data-detail-dialog"
            destroy-on-close
            @closed="selectedRunDetail = null"
          >
            <template v-if="selectedRunDetail" #default>
              <section class="detail-summary">
                <h4>汇总</h4>
                <div class="detail-summary-row">
                  <el-tag>Run ID: {{ selectedRunDetail.run?.id }}</el-tag>
                  <el-tag type="info">创建: {{ selectedRunDetail.run?.created_at }}</el-tag>
                  <el-tag type="success">通过 {{ selectedRunDetail.run?.ok }}</el-tag>
                  <el-tag type="danger">失败 {{ selectedRunDetail.run?.failed }}</el-tag>
                  <el-tag type="warning">提示词修改 {{ selectedRunDetail.run?.updated_prompt_count }} 次</el-tag>
                </div>
              </section>
              <section class="detail-table-section">
                <h4>每张图片明细</h4>
                <el-table :data="selectedRunDetail.details || []" stripe size="small" max-height="40vh">
                  <el-table-column prop="filename" label="图片" min-width="120" show-overflow-tooltip />
                  <el-table-column prop="source_label" label="来源" width="90" />
                  <el-table-column label="预期" width="80">
                    <template #default="{ row }">{{ row.expected_has_issues ? '有问题' : '无问题' }}</template>
                  </el-table-column>
                  <el-table-column label="实际" width="80">
                    <template #default="{ row }">
                      <span v-if="row.actual_has_issues === null">—</span>
                      <span v-else>{{ row.actual_has_issues ? '有问题' : '无问题' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="结果" width="80">
                    <template #default="{ row }">
                      <el-tag :type="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '通过' : '失败' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="attempt_count" label="调用次数" width="90" />
                  <el-table-column prop="retry_count" label="重试" width="70" />
                  <el-table-column prop="message" label="备注" min-width="120" show-overflow-tooltip />
                </el-table>
              </section>
              <!-- 提示词修改记录：修改前 vs 修改后（发给 UI 检测模型的提示词文本） -->
              <section v-if="selectedRunDetail.prompt_versions?.length" class="detail-prompt-versions">
                <h4>提示词修改记录（发给 UI 检测模型的提示词文本）</h4>
                <div v-for="(pv, idx) in selectedRunDetail.prompt_versions" :key="pv.id" class="prompt-version-block">
                  <div class="prompt-version-head">
                    <el-tag size="small">第 {{ idx + 1 }} 次修改</el-tag>
                    <span class="prompt-version-reason">检测原因：{{ pv.detection_reason }}</span>
                    <span class="prompt-version-meta">来源 {{ pv.source_label || '—' }} · {{ pv.created_at }}</span>
                  </div>
                  <div class="prompt-version-diff">
                    <div class="prompt-version-half">
                      <div class="prompt-version-label">修改前（发给 UI 检测模型的提示词）</div>
                      <pre class="prompt-version-text">{{ pv.prompt_before || '（无）' }}</pre>
                    </div>
                    <div class="prompt-version-half">
                      <div class="prompt-version-label">修改后（发给 UI 检测模型的提示词）</div>
                      <pre class="prompt-version-text">{{ pv.prompt_after }}</pre>
                    </div>
                  </div>
                </div>
              </section>
              <section v-if="selectedRunDetail.run?.final_prompt" class="detail-prompt">
                <h4>最终发给 UI 检测模型的提示词</h4>
                <pre class="detail-prompt-content">{{ selectedRunDetail.run.final_prompt }}</pre>
              </section>
            </template>
          </el-dialog>

          <!-- 提示词版本详情弹窗 -->
          <el-dialog
            v-model="showPromptDetailDialog"
            title="提示词版本详情"
            width="75%"
            top="5vh"
            class="data-detail-dialog"
            destroy-on-close
            @closed="selectedPromptDetail = null"
          >
            <template v-if="selectedPromptDetail" #default>
              <div class="prompt-detail-meta">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="ID">{{ selectedPromptDetail.id }}</el-descriptions-item>
                  <el-descriptions-item label="Run ID">{{ selectedPromptDetail.run_id || '—' }}</el-descriptions-item>
                  <el-descriptions-item label="创建时间">{{ selectedPromptDetail.created_at }}</el-descriptions-item>
                  <el-descriptions-item label="来源">{{ selectedPromptDetail.source_label || '—' }}</el-descriptions-item>
                  <el-descriptions-item label="预期有问题">{{ selectedPromptDetail.expected_has_issues ? '是' : '否' }}</el-descriptions-item>
                  <el-descriptions-item label="实际有问题">{{ selectedPromptDetail.result_has_issues ? '是' : '否' }}</el-descriptions-item>
                  <el-descriptions-item label="检测原因" :span="2">{{ selectedPromptDetail.detection_reason }}</el-descriptions-item>
                </el-descriptions>
              </div>
              <div v-if="selectedPromptDetail.prompt_before" class="prompt-detail-block">
                <h4>修改前（发给 UI 检测模型的提示词）</h4>
                <pre class="prompt-detail-text">{{ selectedPromptDetail.prompt_before }}</pre>
              </div>
              <div class="prompt-detail-block">
                <h4>修改后（发给 UI 检测模型的提示词）</h4>
                <pre class="prompt-detail-text">{{ selectedPromptDetail.prompt_after }}</pre>
              </div>
            </template>
          </el-dialog>
        </el-tab-pane>
      </el-tabs>

      <!-- 图片查看器弹窗（全局复用） -->
      <el-dialog
        v-model="showImageViewerDialog"
        :title="'查看：' + imageViewerData.filename"
        width="90%"
        top="2vh"
        class="image-viewer-dialog"
        destroy-on-close
      >
        <div class="iv-layout">
          <div class="iv-image-pane">
            <img v-if="imageViewerData.imageUrl" :src="imageViewerData.imageUrl" class="iv-image" />
          </div>
          <div class="iv-result-pane" v-if="imageViewerData.result">
            <template v-if="imageViewerData.result.success !== false">
              <el-alert
                :title="imageViewerData.result.has_issues ? '检测到显示问题' : '未检测到显示问题'"
                :type="imageViewerData.result.has_issues ? 'warning' : 'success'"
                :closable="false"
                show-icon
                style="margin-bottom: 12px"
              />
              <div class="iv-score">
                得分：<el-tag :type="getScoreType(imageViewerData.result.score)" size="small">{{ imageViewerData.result.score }}</el-tag>
              </div>
              <div v-if="imageViewerData.result.issues?.length" class="iv-issues">
                <h4>问题详情</h4>
                <div v-for="(issue, idx) in imageViewerData.result.issues" :key="idx" class="iv-issue-item">
                  <div class="issue-header">
                    <el-tag :type="getSeverityType(issue.severity)" size="small">{{ issue.severity }}</el-tag>
                    <span class="issue-type">{{ issue.type }}</span>
                  </div>
                  <div class="issue-desc">{{ issue.description }}</div>
                  <div class="issue-location">📍 {{ issue.location }}</div>
                  <div class="issue-suggestion" v-if="issue.suggestion">💡 {{ issue.suggestion }}</div>
                </div>
              </div>
              <div v-if="imageViewerData.result.agent_process?.length" class="iv-agents">
                <h4>Agent 过程</h4>
                <div
                  v-for="(step, idx) in imageViewerData.result.agent_process"
                  :key="idx"
                  class="agent-process-item"
                  :class="{ 'agent-process-hit': step.has_issue, 'agent-process-pass': !step.has_issue }"
                >
                  <div class="agent-process-head">
                    <span class="agent-name">{{ step.agent }}</span>
                    <el-tag :type="step.has_issue ? 'warning' : 'success'" size="small">
                      {{ step.has_issue ? '发现问题' : '未发现问题' }}
                    </el-tag>
                  </div>
                  <div class="agent-reason">{{ step.reason }}</div>
                </div>
              </div>
              <div v-if="imageViewerData.result.summary" class="iv-summary">
                <h4>总结</h4>
                <p>{{ imageViewerData.result.summary }}</p>
              </div>
            </template>
            <template v-else>
              <el-alert title="检测失败" type="error" :closable="false" show-icon />
              <p class="iv-error-msg">{{ imageViewerData.result.message }}</p>
            </template>
          </div>
        </div>
      </el-dialog>
    </main>

    <!-- 页脚 -->
    <footer class="footer">
      <p>© 2025 多语言 OCR Agent. 基于视觉大模型构建</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ocrRecognize, uiCheck, uiCheckBatch, fullAnalyze, leaderTrain, getTrainingRuns, getTrainingRun, getPromptVersions, createTestReport, addTestReportItem, completeTestReport, getTestReports, getTestReport, getReportImageUrl } from './api'

const activeTab = ref('detect')
const previewUrl = ref(null)
const currentFile = ref(null)
const detectFiles = ref([])
const detectFileList = ref([])
const detectFolderInput = ref(null)
const selectedLanguages = ref([])
const ocrResult = ref(null)
const uiResult = ref(null)
const batchUiResults = ref([])
const batchRunningIndex = ref(-1)
const batchConcurrency = ref(2)
const batchTimer = ref({ startMs: 0, elapsedSec: 0, timerId: null })

const startBatchTimer = () => {
  stopBatchTimer()
  batchTimer.value.startMs = Date.now()
  batchTimer.value.elapsedSec = 0
  batchTimer.value.timerId = setInterval(() => {
    batchTimer.value.elapsedSec = ((Date.now() - batchTimer.value.startMs) / 1000).toFixed(1)
  }, 500)
}
const stopBatchTimer = () => {
  if (batchTimer.value.timerId) clearInterval(batchTimer.value.timerId)
  batchTimer.value.timerId = null
  if (batchTimer.value.startMs) {
    batchTimer.value.elapsedSec = ((Date.now() - batchTimer.value.startMs) / 1000).toFixed(1)
  }
}
const batchFinalElapsed = ref('')

const loading = ref({
  ocr: false,
  uiCheck: false,
  batchUiCheck: false,
  full: false,
  leader: false,
  dataRuns: false,
  dataVersions: false
})

const UI_CHECK_PHASES = [
  '结构 Agent：全图结构判断',
  '结构 Agent：生成聚焦区域',
  '专项 Agent：异常换行',
  '专项 Agent：超框/溢出',
  '专项 Agent：截断/重叠/堆叠与汇总'
]

const FULL_ANALYZE_PHASES = [
  'OCR：文本识别',
  ...UI_CHECK_PHASES
]

const uiProgress = ref({
  active: false,
  mode: 'ui',
  phases: [],
  stepIndex: 0,
  stepText: '',
  elapsedSeconds: 0,
  timerId: null
})

const stopUiProgress = () => {
  if (uiProgress.value.timerId) {
    clearInterval(uiProgress.value.timerId)
  }
  uiProgress.value.active = false
  uiProgress.value.timerId = null
}

const startUiProgress = (mode = 'ui') => {
  stopUiProgress()
  const phases = mode === 'full' ? FULL_ANALYZE_PHASES : UI_CHECK_PHASES
  uiProgress.value.active = true
  uiProgress.value.mode = mode
  uiProgress.value.phases = phases
  uiProgress.value.stepIndex = 0
  uiProgress.value.stepText = phases[0]
  uiProgress.value.elapsedSeconds = 0
  uiProgress.value.timerId = setInterval(() => {
    uiProgress.value.elapsedSeconds += 2
    const estimatedStep = Math.min(phases.length - 1, Math.floor(uiProgress.value.elapsedSeconds / 10))
    uiProgress.value.stepIndex = estimatedStep
    uiProgress.value.stepText = phases[estimatedStep]
  }, 2000)
}

// Leader Agent
const problemFiles = ref([])
const noProblemFiles = ref([])
const problemFileList = ref([])
const noProblemFileList = ref([])
const leaderOptions = ref({ maxRounds: 3, sampleSize: 10, requestDelay: 2 })
const leaderResult = ref(null)
const showReportDialog = ref(false)
const problemFolderInput = ref(null)
const noProblemFolderInput = ref(null)

// 数据管理
const dataSubTab = ref('runs')
const trainingRuns = ref([])
const promptVersions = ref([])
const selectedRunDetail = ref(null)
const selectedPromptDetail = ref(null)
const showRunDetailDialog = ref(false)
const showPromptDetailDialog = ref(false)
const loadTrainingRuns = async () => {
  loading.value.dataRuns = true
  try {
    const res = await getTrainingRuns(50)
    trainingRuns.value = res.data || []
  } catch (e) {
    ElMessage.error('加载训练记录失败: ' + (e.response?.data?.detail || e.message))
    trainingRuns.value = []
  } finally {
    loading.value.dataRuns = false
  }
}
const loadPromptVersions = async () => {
  loading.value.dataVersions = true
  try {
    const res = await getPromptVersions(50)
    promptVersions.value = res.data || []
  } catch (e) {
    ElMessage.error('加载提示词版本失败: ' + (e.response?.data?.detail || e.message))
    promptVersions.value = []
  } finally {
    loading.value.dataVersions = false
  }
}
const openRunDetail = async (runId) => {
  try {
    const res = await getTrainingRun(runId)
    selectedRunDetail.value = res.data
    showRunDetailDialog.value = true
  } catch (e) {
    ElMessage.error('加载详情失败: ' + (e.response?.data?.detail || e.message))
  }
}
const openPromptDetail = (row) => {
  selectedPromptDetail.value = row
  showPromptDetailDialog.value = true
}
watch(activeTab, (tab) => {
  if (tab === 'data') {
    loadTrainingRuns()
    loadPromptVersions()
  }
  if (tab === 'reports') {
    loadTestReports()
  }
})

const openReportDialog = () => {
  showReportDialog.value = true
}

const IMAGE_EXT = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
const isImageFile = (file) => {
  const name = (file.name || '').toLowerCase()
  return IMAGE_EXT.some(ext => name.endsWith(ext)) || (file.type || '').startsWith('image/')
}

const triggerFolderPick = (type) => {
  const el = type === 'problem' ? problemFolderInput.value : noProblemFolderInput.value
  if (el) {
    el.value = ''
    el.click()
  }
}

const handleLeaderFolderChange = (e, type) => {
  const files = e.target.files
  if (!files || !files.length) return
  const list = []
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    if (!isImageFile(file)) continue
    list.push({ uid: `folder-${type}-${i}-${file.name}`, name: file.name, raw: file })
  }
  if (type === 'problem') {
    problemFileList.value = list
    problemFiles.value = list.map(f => f.raw)
    ElMessage.success(`已选择「有问题的图片」文件夹，共 ${list.length} 张图片`)
  } else {
    noProblemFileList.value = list
    noProblemFiles.value = list.map(f => f.raw)
    ElMessage.success(`已选择「无问题的图片」文件夹，共 ${list.length} 张图片`)
  }
  e.target.value = ''
}

const handleLeaderFileChange = (file, type) => {
  const raw = file.raw
  if (!raw || !raw.type.startsWith('image/')) return
  const item = { uid: file.uid, name: file.name, raw }
  if (type === 'problem') {
    problemFileList.value = [...problemFileList.value, item]
    problemFiles.value = problemFileList.value.map(f => f.raw)
  } else {
    noProblemFileList.value = [...noProblemFileList.value, item]
    noProblemFiles.value = noProblemFileList.value.map(f => f.raw)
  }
}
const handleLeaderFileRemove = (file, type) => {
  if (type === 'problem') {
    problemFileList.value = problemFileList.value.filter(f => f.uid !== file.uid)
    problemFiles.value = problemFileList.value.map(f => f.raw)
  } else {
    noProblemFileList.value = noProblemFileList.value.filter(f => f.uid !== file.uid)
    noProblemFiles.value = noProblemFileList.value.map(f => f.raw)
  }
}
const clearLeaderFiles = () => {
  problemFiles.value = []
  noProblemFiles.value = []
  problemFileList.value = []
  noProblemFileList.value = []
  leaderResult.value = null
}
const leaderResultRef = ref(null)
const handleLeaderTrain = async () => {
  if (!problemFiles.value.length && !noProblemFiles.value.length) return
  loading.value.leader = true
  leaderResult.value = null
  try {
    const res = await leaderTrain(
      problemFiles.value,
      noProblemFiles.value,
      leaderOptions.value.maxRounds,
      leaderOptions.value.sampleSize,
      leaderOptions.value.requestDelay
    )
    leaderResult.value = res.data
    ElMessage.success('训练完成')
    await nextTick()
    leaderResultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e) {
    const msg = e.response?.data?.detail || e.message
    leaderResult.value = {
      success: false,
      message: '训练失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)),
      total: 0,
      ok: 0,
      failed: 0,
      details: [],
      updated_prompt_count: 0,
    }
    ElMessage.error('训练失败，请查看下方结果区域')
    await nextTick()
    leaderResultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } finally {
    loading.value.leader = false
  }
}

const handleFileChange = (file) => {
  currentFile.value = file.raw
  previewUrl.value = URL.createObjectURL(file.raw)
  ocrResult.value = null
  uiResult.value = null
}

const triggerDetectFolderPick = () => {
  if (detectFolderInput.value) {
    detectFolderInput.value.value = ''
    detectFolderInput.value.click()
  }
}

const handleDetectFileChange = (file) => {
  const raw = file?.raw
  if (!raw || !raw.type?.startsWith('image/')) return
  const item = { uid: file.uid, name: file.name || raw.name || `image_${Date.now()}`, raw }
  const exists = detectFileList.value.some(f => f.uid === item.uid)
  if (!exists) {
    detectFileList.value = [...detectFileList.value, item]
    detectFiles.value = detectFileList.value.map(f => f.raw)
  }
  currentFile.value = raw
  previewUrl.value = URL.createObjectURL(raw)
  ocrResult.value = null
  uiResult.value = null
}

const handleDetectFolderChange = (e) => {
  const files = e.target.files
  if (!files || !files.length) return
  const existingKeys = new Set(
    detectFileList.value.map(f => `${f.name}_${f.raw?.size || 0}_${f.raw?.lastModified || 0}`)
  )
  let added = 0
  let firstAddedRaw = null
  const appended = [...detectFileList.value]
  for (let i = 0; i < files.length; i++) {
    const raw = files[i]
    if (!isImageFile(raw)) continue
    const key = `${raw.name}_${raw.size || 0}_${raw.lastModified || 0}`
    if (existingKeys.has(key)) continue
    existingKeys.add(key)
    const relativeName = raw.webkitRelativePath || raw.name || `image_${Date.now()}_${i}`
    appended.push({
      uid: `detect-folder-${i}-${relativeName}`,
      name: relativeName,
      raw
    })
    if (!firstAddedRaw) firstAddedRaw = raw
    added += 1
  }
  detectFileList.value = appended
  detectFiles.value = detectFileList.value.map(f => f.raw)
  if (firstAddedRaw) {
    currentFile.value = firstAddedRaw
    previewUrl.value = URL.createObjectURL(firstAddedRaw)
    ocrResult.value = null
    uiResult.value = null
  }
  ElMessage.success(`文件夹导入完成，新增 ${added} 张图片`)
  e.target.value = ''
}

const handleDetectFileRemove = (file) => {
  detectFileList.value = detectFileList.value.filter(f => f.uid !== file.uid)
  detectFiles.value = detectFileList.value.map(f => f.raw)
  if (!detectFileList.value.length) {
    previewUrl.value = null
    currentFile.value = null
    ocrResult.value = null
    uiResult.value = null
    return
  }
  // 删除当前预览项时，回退到队列首张
  const fallback = detectFileList.value[0]
  currentFile.value = fallback.raw
  previewUrl.value = URL.createObjectURL(fallback.raw)
}

// 处理粘贴事件
const handlePaste = async (event) => {
  const items = event.clipboardData?.items
  if (!items) return

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    // 检查是否是图片类型
    if (item.type.indexOf('image') !== -1) {
      event.preventDefault()
      const file = item.getAsFile()
      if (file) {
        // 创建 File 对象包装，模拟 el-upload 的格式
        const fileWrapper = {
          raw: file,
          name: file.name || `粘贴图片_${Date.now()}.${file.type.split('/')[1]}`,
          size: file.size,
          type: file.type
        }
        handleDetectFileChange(fileWrapper)
        ElMessage.success('已粘贴图片')
      }
      break
    }
  }
}

// 组件挂载时添加粘贴事件监听
onMounted(() => {
  document.addEventListener('paste', handlePaste)
})

// 组件卸载时移除事件监听
onUnmounted(() => {
  document.removeEventListener('paste', handlePaste)
  stopUiProgress()
  stopBatchTimer()
})

const handleOCR = async () => {
  if (!currentFile.value) return
  loading.value.ocr = true
  try {
    const languages = selectedLanguages.value.join(',') || null
    const res = await ocrRecognize(currentFile.value, languages)
    ocrResult.value = res.data
    ElMessage.success('文字识别完成')
  } catch (e) {
    ElMessage.error('识别失败: ' + e.message)
  } finally {
    loading.value.ocr = false
  }
}

const handleUICheck = async () => {
  if (!currentFile.value) return
  loading.value.uiCheck = true
  startUiProgress('ui')
  try {
    const res = await uiCheck(currentFile.value)
    uiResult.value = res.data
    ElMessage.success('UI 检测完成')
  } catch (e) {
    const msg = e.response?.data?.detail || e.response?.data?.message || e.message
    uiResult.value = {
      success: false,
      has_issues: false,
      issues: [],
      summary: '',
      score: 0,
      structure_ok: null,
      structure_assessment: '',
      agent_process: [],
      message: 'UI 检测失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    ElMessage.error('检测失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)))
  } finally {
    loading.value.uiCheck = false
    stopUiProgress()
  }
}

const handleBatchUICheck = async () => {
  if (!detectFiles.value.length) return
  loading.value.batchUiCheck = true
  batchFinalElapsed.value = ''
  startBatchTimer()
  const total = detectFileList.value.length
  batchUiResults.value = detectFileList.value.map(f => ({
    filename: f.name,
    status: 'pending',
    success: null,
    result: null,
    message: '等待检测...'
  }))
  batchRunningIndex.value = 0

  try {
    const reportRes = await createTestReport(total)
    currentReportId.value = reportRes.data.report_id
    const concurrency = batchConcurrency.value
    let nextIdx = 0
    let doneCount = 0

    const worker = async () => {
      while (true) {
        const idx = nextIdx
        if (idx >= total) break
        nextIdx++
        batchUiResults.value[idx].status = 'running'
        try {
          const res = await addTestReportItem(currentReportId.value, detectFileList.value[idx].raw)
          const data = res.data
          doneCount++
          batchUiResults.value[idx] = {
            filename: data.filename || detectFileList.value[idx].name,
            status: 'done',
            success: data.success !== false,
            result: data.success !== false ? data : undefined,
            message: data.message || ''
          }
          if (data.success !== false) {
            uiResult.value = data
          }
        } catch (e) {
          doneCount++
          batchUiResults.value[idx] = {
            filename: detectFileList.value[idx].name,
            status: 'done',
            success: false,
            result: undefined,
            message: e.response?.data?.detail || e.message
          }
        }
      }
    }

    await Promise.all(Array.from({ length: concurrency }, () => worker()))
    await completeTestReport(currentReportId.value)
    stopBatchTimer()

    const elapsed = batchTimer.value.elapsedSec
    batchFinalElapsed.value = elapsed
    const okCount = batchUiResults.value.filter(r => r.success).length
    const issueCount = batchUiResults.value.filter(r => r.result?.has_issues).length
    ElMessage.success(`批量检测完成：${okCount}/${total} 成功，${issueCount} 张有问题，耗时 ${elapsed}s，报告已保存`)
  } catch (e) {
    stopBatchTimer()
    batchFinalElapsed.value = batchTimer.value.elapsedSec
    const msg = e.response?.data?.detail || e.response?.data?.message || e.message
    ElMessage.error('批量检测失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)))
  } finally {
    loading.value.batchUiCheck = false
    batchRunningIndex.value = -1
    stopUiProgress()
  }
}

const handleFullAnalyze = async () => {
  if (!currentFile.value) return
  loading.value.full = true
  startUiProgress('full')
  try {
    const languages = selectedLanguages.value.join(',') || null
    const res = await fullAnalyze(currentFile.value, languages)
    ocrResult.value = res.data.ocr
    uiResult.value = res.data.ui_check
    ElMessage.success('综合分析完成')
  } catch (e) {
    const msg = e.response?.data?.detail || e.response?.data?.message || e.message
    uiResult.value = {
      success: false,
      has_issues: false,
      issues: [],
      summary: '',
      score: 0,
      structure_ok: null,
      structure_assessment: '',
      agent_process: [],
      message: '综合分析失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    ElMessage.error('分析失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)))
  } finally {
    loading.value.full = false
    stopUiProgress()
  }
}

const clearAll = () => {
  previewUrl.value = null
  currentFile.value = null
  detectFiles.value = []
  detectFileList.value = []
  batchUiResults.value = []
  batchRunningIndex.value = -1
  selectedLanguages.value = []
  ocrResult.value = null
  uiResult.value = null
}

const currentReportId = ref(null)

const openBatchResult = (index) => {
  const row = batchUiResults.value[index]
  if (!row) return
  const f = detectFileList.value[index]
  if (f?.raw) {
    currentFile.value = f.raw
    previewUrl.value = URL.createObjectURL(f.raw)
  }
  if (row.success) {
    uiResult.value = row.result
  } else {
    uiResult.value = {
      success: false,
      has_issues: false,
      issues: [],
      summary: '',
      score: 0,
      structure_ok: null,
      structure_assessment: '',
      agent_process: [],
      message: 'UI 检测失败: ' + row.message
    }
  }
}

// --------------- 测试报告 ---------------
const testReports = ref([])
const selectedReport = ref(null)
const showReportDetailDialog = ref(false)
const reportFilterStatus = ref('all')
const reportFilterIssueType = ref('all')
const showImageViewerDialog = ref(false)
const imageViewerData = ref({ imageUrl: '', result: null, filename: '' })

const ISSUE_TYPE_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '异常换行', value: '异常换行' },
  { label: '文字超框/溢出', value: '文字超框/溢出' },
  { label: '文字截断', value: '文字截断' },
  { label: '文字重叠', value: '文字重叠' },
  { label: 'UI堆叠', value: 'UI堆叠' },
  { label: '乱码/编码问题', value: '乱码/编码问题' },
]

const loadTestReports = async () => {
  try {
    const res = await getTestReports(100)
    testReports.value = res.data || []
  } catch (e) {
    ElMessage.error('加载测试报告失败: ' + (e.response?.data?.detail || e.message))
  }
}

const openTestReportDetail = async (reportId) => {
  try {
    const res = await getTestReport(reportId)
    selectedReport.value = res.data
    reportFilterStatus.value = 'all'
    reportFilterIssueType.value = 'all'
    showReportDetailDialog.value = true
  } catch (e) {
    ElMessage.error('加载报告详情失败: ' + (e.response?.data?.detail || e.message))
  }
}

const filteredReportItems = () => {
  if (!selectedReport.value?.items) return []
  let items = selectedReport.value.items
  if (reportFilterStatus.value === 'has_issues') {
    items = items.filter(i => i.success && i.has_issues)
  } else if (reportFilterStatus.value === 'no_issues') {
    items = items.filter(i => i.success && !i.has_issues)
  } else if (reportFilterStatus.value === 'failed') {
    items = items.filter(i => !i.success)
  }
  if (reportFilterIssueType.value !== 'all') {
    items = items.filter(i =>
      i.issues && i.issues.some(issue => issue.type === reportFilterIssueType.value)
    )
  }
  return items
}

const openImageViewer = (item, reportId) => {
  imageViewerData.value = {
    imageUrl: getReportImageUrl(reportId, item.filename),
    result: item,
    filename: item.filename,
  }
  showImageViewerDialog.value = true
}

const openBatchImageViewer = (index) => {
  const row = batchUiResults.value[index]
  if (!row) return
  const f = detectFileList.value[index]
  const localUrl = f?.raw ? URL.createObjectURL(f.raw) : ''
  imageViewerData.value = {
    imageUrl: localUrl,
    result: row.success ? row.result : { success: false, message: row.message },
    filename: row.filename,
  }
  showImageViewerDialog.value = true
}

const getIssueTypesText = (issues) => {
  if (!issues || !issues.length) return '—'
  const types = [...new Set(issues.map(i => i.type))]
  return types.join('、')
}

const getScoreType = (score) => {
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'danger'
}

const getSeverityType = (severity) => {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

const getUIStatusTitle = (result) => {
  // 如果得分很低（< 60），即使 has_issues 为 false，也应该显示警告
  if (result.score < 60 && !result.has_issues) {
    return '检测结果异常，得分过低'
  }
  return result.has_issues ? '检测到显示问题' : '未检测到显示问题'
}

const getUIStatusType = (result) => {
  // 如果得分很低（< 60），显示警告
  if (result.score < 60) {
    return 'warning'
  }
  return result.has_issues ? 'warning' : 'success'
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
}

.app-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  text-align: center;
  color: white;
  padding: 30px 0;
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.logo-icon {
  font-size: 48px;
}

.header h1 {
  font-size: 32px;
  font-weight: 600;
}

.subtitle {
  margin-top: 10px;
  opacity: 0.9;
  font-size: 16px;
}

.main-content {
  flex: 1;
}

.upload-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.upload-area {
  width: 100%;
}

.upload-area .el-upload-dragger {
  width: 100%;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.upload-placeholder {
  text-align: center;
}

.upload-icon {
  font-size: 48px;
  color: #909399;
  margin-bottom: 10px;
}

.upload-text {
  color: #606266;
  font-size: 16px;
}

.upload-hint {
  color: #909399;
  font-size: 12px;
  margin-top: 6px;
}

.preview-image {
  max-width: 100%;
  max-height: 400px;
  object-fit: contain;
}

.language-select {
  margin-top: 16px;
}

.action-buttons {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-summary {
  margin-top: 10px;
  color: #606266;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.batch-concurrency-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
}

.batch-progress-panel {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  color: #ad6800;
  font-size: 13px;
}

.batch-timer, .batch-done-count {
  font-weight: 600;
}
.batch-header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-elapsed-tag {
  font-size: 12px;
  color: #909399;
  background: #f5f7fa;
  padding: 2px 8px;
  border-radius: 4px;
}
.detect-upload-actions {
  margin-top: 10px;
  display: flex;
  justify-content: flex-start;
}

.ui-progress-panel {
  margin-top: 14px;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #fafafa;
  padding: 12px;
}

.ui-progress-title {
  font-weight: 600;
  color: #303133;
}

.ui-progress-current {
  margin-top: 6px;
  color: #606266;
}

.ui-progress-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}

.ui-progress-steps {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ui-progress-step {
  font-size: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 999px;
  padding: 3px 10px;
  color: #909399;
  background: #fff;
}

.ui-progress-step-active {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}

.results-area {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 20px;
}

.result-card {
  height: fit-content;
}

.result-section {
  margin-top: 16px;
}

.result-section h4 {
  font-size: 14px;
  color: #606266;
  margin-bottom: 8px;
}

.language-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.lang-tag {
  margin-right: 0;
}

.text-content {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.6;
  max-height: 300px;
  overflow-y: auto;
}

.issues-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.issue-item {
  background: #fef0f0;
  border-radius: 8px;
  padding: 12px;
  border-left: 4px solid #f56c6c;
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.issue-type {
  font-weight: 600;
  color: #303133;
}

.issue-desc {
  color: #606266;
  margin-bottom: 6px;
}

.issue-location, .issue-suggestion {
  font-size: 13px;
  color: #909399;
}

.summary-content {
  background: #f0f9eb;
  padding: 12px;
  border-radius: 6px;
  color: #67c23a;
  font-size: 14px;
}
.structure-assessment {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px;
  border-radius: 6px;
  font-size: 14px;
}
.structure-assessment.structure-ok {
  background: #f0f9eb;
  color: #67c23a;
}
.structure-assessment.structure-ng {
  background: #fdf6ec;
  color: #e6a23c;
}
.structure-assessment .structure-text {
  flex: 1;
  line-height: 1.5;
}
.agent-process-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.agent-process-item {
  border-radius: 8px;
  border: 1px solid #ebeef5;
  padding: 10px 12px;
  background: #fff;
}
.agent-process-item.agent-process-pass {
  border-left: 4px solid #67c23a;
}
.agent-process-item.agent-process-hit {
  border-left: 4px solid #e6a23c;
}
.agent-process-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.agent-step-index {
  font-size: 12px;
  color: #909399;
}
.agent-name {
  font-weight: 600;
  color: #303133;
}
.agent-issue-type {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}
.agent-reason {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}
.agent-timing {
  margin-left: 8px;
  font-size: 11px;
  color: #909399;
  background: #f5f7fa;
  padding: 1px 6px;
  border-radius: 4px;
}
.timing-info {
  font-size: 12px;
  color: #909399;
  padding: 6px 0;
}

.error-message {
  color: #f56c6c;
  text-align: center;
  padding: 20px;
}

.footer {
  text-align: center;
  color: white;
  opacity: 0.8;
  padding: 20px 0;
  font-size: 14px;
}

/* Leader Agent */
.main-tabs {
  width: 100%;
}
.main-tabs .el-tabs__header { margin-bottom: 16px; }
.main-tabs .el-tabs__item { color: rgba(255,255,255,0.8); }
.main-tabs .el-tabs__item.is-active { color: #fff; }
.main-tabs .el-tabs__nav-wrap::after { display: none; }
.main-tabs .el-tabs__ink-bar { background: #fff; }
.main-tabs .el-tabs__active-bar { background: #fff; }
.main-tabs .el-tabs__content { overflow: visible; }

.leader-card .card-desc {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
  margin-left: 8px;
}
.leader-card .card-header {
  flex-wrap: wrap;
  gap: 8px;
}

.leader-upload-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}
@media (max-width: 768px) {
  .leader-upload-row { grid-template-columns: 1fr; }
}
.leader-upload-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.leader-upload-label {
  font-weight: 600;
  color: #303133;
}
.leader-upload-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.leader-folder-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}
.leader-upload-divider {
  color: #909399;
  font-size: 12px;
}
.leader-upload-inline .el-upload {
  display: inline-block;
}
.leader-upload .el-upload-dragger {
  width: 100%;
  min-height: 160px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 16px;
}
.leader-upload-icon {
  font-size: 40px;
  color: #909399;
  margin-bottom: 8px;
}
.leader-upload-text {
  color: #606266;
  font-size: 14px;
}
.leader-upload-hint {
  color: #909399;
  font-size: 12px;
}
.leader-file-count {
  font-size: 12px;
  color: #909399;
}
.leader-options {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.leader-option {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #606266;
}
.leader-option span { white-space: nowrap; }
.leader-actions {
  margin-bottom: 20px;
}
.leader-timeout-hint {
  font-size: 12px;
  color: #909399;
  margin: 10px 0 0;
}
.leader-result {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #ebeef5;
}
.leader-result-heading {
  font-size: 16px;
  color: #303133;
  margin-bottom: 12px;
}
.leader-stats {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.leader-report-btn {
  margin-left: 8px;
}
.leader-details-section {
  margin-top: 20px;
}
.leader-details-title {
  font-size: 14px;
  color: #303133;
  margin-bottom: 12px;
}
.leader-details-table {
  width: 100%;
}
.leader-prompt-collapse {
  margin-top: 16px;
}
.leader-final-prompt {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  max-height: 300px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  margin: 0;
}

/* 测试报告弹窗 */
.report-dialog .el-dialog__header {
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
}
.report-dialog-title {
  font-size: 18px;
  font-weight: 600;
}
.report-page {
  padding: 0 4px;
}
.report-summary {
  margin-bottom: 24px;
}
.report-summary h4,
.report-details h4,
.report-prompt h4 {
  font-size: 14px;
  color: #303133;
  margin-bottom: 12px;
}
.report-summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 12px;
}
@media (max-width: 768px) {
  .report-summary-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
.report-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}
.report-card-value {
  display: block;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}
.report-card-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.report-card-ok .report-card-value { color: #67c23a; }
.report-card-fail .report-card-value { color: #f56c6c; }
.report-card-warn .report-card-value { color: #e6a23c; }
.report-message {
  font-size: 13px;
  color: #606266;
  margin: 0;
}
.report-details {
  margin-bottom: 24px;
}
.report-table {
  width: 100%;
}
.report-no-details {
  color: #909399;
  font-size: 13px;
  margin: 0;
}
.report-prompt-content {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  margin: 0;
}

/* 数据管理 */
.data-card .card-desc {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
  margin-left: 8px;
}
.data-sub-tabs {
  margin-top: 0;
}
.data-toolbar {
  margin-bottom: 12px;
}
.data-table {
  width: 100%;
}
.data-empty {
  color: #909399;
  font-size: 13px;
  padding: 24px;
  text-align: center;
  margin: 0;
}
.data-detail-dialog .el-dialog__body {
  max-height: 75vh;
  overflow-y: auto;
}
.detail-summary {
  margin-bottom: 20px;
}
.detail-summary h4,
.detail-table-section h4,
.detail-prompt h4,
.detail-prompt-versions h4,
.prompt-detail-block h4 {
  font-size: 14px;
  color: #303133;
  margin-bottom: 10px;
}
.detail-prompt-versions {
  margin-bottom: 20px;
}
.prompt-version-block {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafafa;
}
.prompt-version-block:last-child {
  margin-bottom: 0;
}
.prompt-version-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}
.prompt-version-reason {
  font-size: 13px;
  color: #606266;
  flex: 1;
  min-width: 0;
}
.prompt-version-meta {
  font-size: 12px;
  color: #909399;
}
.prompt-version-diff {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 768px) {
  .prompt-version-diff {
    grid-template-columns: 1fr;
  }
}
.prompt-version-half {
  min-width: 0;
}
.prompt-version-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 500;
}
.prompt-version-text {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
  background: #fff;
  padding: 10px;
  border-radius: 6px;
  margin: 0;
  border: 1px solid #ebeef5;
}
.detail-summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.detail-table-section {
  margin-bottom: 20px;
}
.detail-prompt-content,
.prompt-detail-text {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  margin: 0;
}
.prompt-detail-meta {
  margin-bottom: 20px;
}
.prompt-detail-block {
  margin-bottom: 16px;
}
.prompt-detail-block:last-child {
  margin-bottom: 0;
}

/* 批量结果增强 */
.status-running-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  margin-right: 4px;
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.score-low {
  color: #f56c6c;
  font-weight: 600;
}
.op-placeholder {
  color: #c0c4cc;
  font-size: 12px;
}
.stat-ok { color: #67c23a; font-weight: 600; }
.stat-warn { color: #e6a23c; font-weight: 600; }
.stat-fail { color: #f56c6c; font-weight: 600; }

/* 测试报告列表 */
.report-list-card {
  margin-bottom: 20px;
}

/* 报告详情弹窗 */
.report-detail-dialog .el-dialog__body {
  max-height: 82vh;
  overflow-y: auto;
  padding: 16px 20px;
}
.rpt-summary {
  margin-bottom: 16px;
}
.rpt-summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 10px;
}
@media (max-width: 768px) {
  .rpt-summary-cards { grid-template-columns: repeat(2, 1fr); }
}
.rpt-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}
.rpt-card-value {
  display: block;
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}
.rpt-card-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.rpt-card-ok .rpt-card-value { color: #67c23a; }
.rpt-card-warn .rpt-card-value { color: #e6a23c; }
.rpt-card-fail .rpt-card-value { color: #f56c6c; }
.rpt-time-info {
  font-size: 12px;
  color: #909399;
}

/* 筛选栏 */
.rpt-filters {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 10px 12px;
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}
.rpt-filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
}
.rpt-filter-count {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

/* 图片查看器弹窗 */
.image-viewer-dialog .el-dialog__body {
  padding: 12px 16px;
  max-height: 85vh;
  overflow-y: auto;
}
.iv-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  min-height: 400px;
}
@media (max-width: 900px) {
  .iv-layout { grid-template-columns: 1fr; }
}
.iv-image-pane {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 8px;
  max-height: 75vh;
  overflow: auto;
}
.iv-image {
  max-width: 100%;
  max-height: 72vh;
  object-fit: contain;
  border-radius: 4px;
}
.iv-result-pane {
  max-height: 75vh;
  overflow-y: auto;
  padding-right: 4px;
}
.iv-score {
  margin-bottom: 12px;
  font-size: 14px;
}
.iv-issues h4,
.iv-agents h4,
.iv-summary h4 {
  font-size: 14px;
  color: #303133;
  margin-bottom: 8px;
  margin-top: 16px;
}
.iv-issue-item {
  background: #fef0f0;
  border-radius: 8px;
  padding: 10px 12px;
  border-left: 4px solid #f56c6c;
  margin-bottom: 8px;
}
.iv-summary p {
  background: #f0f9eb;
  padding: 10px 12px;
  border-radius: 6px;
  color: #67c23a;
  font-size: 13px;
  margin: 0;
}
.iv-error-msg {
  color: #f56c6c;
  margin-top: 12px;
  font-size: 14px;
}
</style>
