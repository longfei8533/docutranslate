<template>
    <div class="task-list-item" :class="{'task-list-item-selected': task.selected}">
        <div class="task-row" @click="task.expanded = !task.expanded">
            <div class="task-cell task-select" @click.stop>
                <input type="checkbox" v-model="task.selected" :aria-label="t('selectTask')">
            </div>
            <div class="task-cell task-file-cell">
                <Heroicon name="DocumentTextIcon" class="w-5 h-5 text-gray-400 flex-shrink-0" />
                <div class="min-w-0">
                    <div class="task-file-name" :title="task.fileName">{{ task.fileName || t('taskCardIdPlaceholder') }}</div>
                    <div class="task-file-meta">{{ workflowLabel }}<span v-if="task.backendId"> · {{ task.backendId }}</span></div>
                </div>
            </div>
            <div class="task-cell">
                <span class="task-status" :class="statusClass">
                    <span v-if="task.isProcessing" class="task-spinner"></span>
                    {{ statusLabel }}
                </span>
            </div>
            <div class="task-cell task-progress-cell">
                <div class="task-progress-track">
                    <div class="task-progress-value" :class="progressClass" :style="{width: `${task.progressPercent || 0}%`}"></div>
                </div>
                <span>{{ task.progressPercent || 0 }}%</span>
            </div>
            <div class="task-cell task-rate" :class="rateClass">{{ successRate }}</div>
            <div class="task-cell task-duration">{{ duration }}</div>
            <div class="task-cell task-actions" @click.stop>
                <button v-if="task.downloads?.html" class="task-icon-button" :title="t('taskCardPreviewBtn')" @click="onOpenPreview">
                    <Heroicon name="EyeIcon" class="w-4 h-4" />
                </button>
                <Dropdown v-if="task.downloads && Object.keys(task.downloads).length">
                    <template #trigger>
                        <button class="task-icon-button" :title="t('taskCardDownloadBtn')">
                            <Heroicon name="ArrowDownTrayIcon" class="w-4 h-4" />
                        </button>
                    </template>
                    <a v-for="(link, key) in task.downloads" :key="key" :href="link" class="task-menu-link">
                        <Heroicon :name="getDownloadIcon(key).name" class="w-4 h-4" />
                        {{ downloadLabel(key) }}
                    </a>
                    <a v-if="task.downloads.html" href="#" @click.stop.prevent="onPrintPdf" class="task-menu-link">
                        <Heroicon name="DocumentTextIcon" class="w-4 h-4" /> PDF
                    </a>
                </Dropdown>
                <button v-if="needsFile" class="task-row-button" @click="triggerFileInput">
                    {{ t('reselectFile') }}
                </button>
                <button v-else-if="!isCompleted" class="task-row-button" :class="task.isTranslating ? 'task-stop-button' : 'task-start-button'"
                        :disabled="task.initializing" @click="onToggleTaskState">
                    <Heroicon :name="task.isTranslating ? 'StopIcon' : (task.isFinished ? 'ArrowPathIcon' : 'PlayIcon')" class="w-4 h-4" />
                    {{ actionLabel }}
                </button>
                <button class="task-icon-button task-remove-button" :title="t('removeTask')" @click="onRemoveTask">
                    <Heroicon name="TrashIcon" class="w-4 h-4" />
                </button>
                <Heroicon :name="task.expanded ? 'ChevronUpIcon' : 'ChevronDownIcon'" class="w-4 h-4 text-gray-400" />
            </div>
        </div>

        <div v-if="task.expanded" class="task-detail">
            <div class="task-detail-main">
                <div class="task-detail-heading">
                    <span>{{ task.statusMessage || statusLabel }}</span>
                    <button v-if="task.logs" class="task-icon-button" :title="t('copyLogsTooltip')" @click="onCopyLog">
                        <Heroicon name="ClipboardDocumentIcon" class="w-4 h-4" />
                    </button>
                </div>
                <div class="task-log" :id="'log-' + task.uiId" v-html="task.logs || t('noLogsYet')"></div>
            </div>
            <div class="task-detail-side">
                <div class="task-stat-grid">
                    <div><span>Input</span><strong>{{ formatTokens(stats.input_tokens) }}</strong></div>
                    <div><span>Cache</span><strong>{{ formatTokens(stats.cached_tokens) }}</strong></div>
                    <div><span>Output</span><strong>{{ formatTokens(stats.output_tokens) }}</strong></div>
                    <div><span>Reason</span><strong>{{ formatTokens(stats.reasoning_tokens) }}</strong></div>
                    <div><span>Total</span><strong>{{ formatTokens(stats.total_tokens) }}</strong></div>
                    <div><span>{{ t('unresolvedErrors') }}</span><strong>{{ stats.unresolved_errors || 0 }}</strong></div>
                </div>
                <div v-if="task.attachment && Object.keys(task.attachment).length" class="task-attachments">
                    <span>{{ t('taskCardAttachmentBtn') }}:</span>
                    <a v-for="(link, name) in task.attachment" :key="name" :href="link">{{ name }}</a>
                </div>
            </div>
            <input type="file" class="hidden" :id="'fileInput-' + task.uiId" @change="onFileSelect">
        </div>
        <input v-else type="file" class="hidden" :id="'fileInput-' + task.uiId" @change="onFileSelect">
    </div>
</template>

<script setup>
import { computed } from 'vue';
import { getDownloadIcon } from '../../utils/helpers';
import Dropdown from '../ui/Dropdown.vue';
import Heroicon from '../ui/Heroicon.vue';

const props = defineProps({ t: Function, task: Object, completed: Boolean });
const emit = defineEmits(['removeTask', 'fileSelect', 'triggerFileInput', 'copyLog', 'openPreview', 'printPdf', 'toggleTaskState']);

const stats = computed(() => props.task.statistics?.total || {});
const isCompleted = computed(() => props.completed || props.task.phase === 'completed');
const needsFile = computed(() => !isCompleted.value && props.task.isFinished && !props.task.file);
const workflowLabel = computed(() => props.task.detectedWorkflow || tValue('workflowAuto'));
const statusLabel = computed(() => {
    if (props.task.phase === 'queued' && props.task.queuePosition) {
        return props.t('taskCardQueuePosition', {n: props.task.queuePosition, total: props.task.queueTotal});
    }
    return tValue(`taskStatus_${props.task.phase}`);
});
const statusClass = computed(() => `task-status-${props.task.phase}`);
const progressClass = computed(() => props.task.phase === 'failed' || props.task.phase === 'expired' ? 'task-progress-danger' : (props.task.phase === 'partial' ? 'task-progress-warning' : ''));
const successRate = computed(() => {
    if (!stats.value.request_count) return '—';
    return `${Math.max(0, (1 - Number(stats.value.unresolved_error_rate || 0)) * 100).toFixed(1)}%`;
});
const rateClass = computed(() => {
    if (!stats.value.request_count) return '';
    const rate = Number(stats.value.unresolved_error_rate || 0);
    return rate === 0 ? 'text-success' : (rate < 0.3 ? 'text-warning' : 'text-danger');
});
const duration = computed(() => {
    if (!props.task.startTime) return '—';
    const end = props.task.endTime || (props.task.isTranslating ? Date.now() / 1000 : props.task.startTime);
    const seconds = Math.max(0, end - props.task.startTime);
    return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s` : `${Math.round(seconds)}s`;
});
const actionLabel = computed(() => props.task.initializing ? props.t('btn_initializing') : (props.task.isTranslating ? props.t('btn_cancelTranslation') : (props.task.isFinished ? props.t('btn_reTranslate') : props.t('taskCardStartBtn'))));

function tValue(key) {
    const value = props.t(key);
    return value === key ? key.replace('taskStatus_', '') : value;
}
const formatTokens = value => !value ? '0' : (value >= 1000 ? `${(value / 1000).toFixed(1)}K` : String(value));
const downloadLabel = key => key === 'markdown_zip' ? props.t('downloadMdZip') : (key === 'markdown' ? props.t('downloadMdEmbedded') : key.toUpperCase());
const onRemoveTask = () => emit('removeTask', props.task);
const onFileSelect = event => emit('fileSelect', event, props.task);
const triggerFileInput = () => emit('triggerFileInput', props.task.uiId);
const onCopyLog = event => emit('copyLog', event, props.task.logs);
const onOpenPreview = () => emit('openPreview', props.task);
const onPrintPdf = () => emit('printPdf', props.task.downloads.html);
const onToggleTaskState = () => emit('toggleTaskState', props.task);
</script>
