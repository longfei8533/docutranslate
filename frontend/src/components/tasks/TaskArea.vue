<template>
    <main class="task-manager" @dragover.prevent="dragging = true" @dragleave.self="dragging = false" @drop.prevent="onDrop">
        <input ref="fileInput" type="file" multiple class="hidden" @change="handleFilesSelect">
        <input ref="folderInput" type="file" class="hidden" webkitdirectory directory multiple @change="handleFolderSelect">

        <div class="task-toolbar">
            <div>
                <h2>{{ t('taskManagerTitle') }}</h2>
                <span>{{ t('taskManagerSummary', {active: activeTasks.length, completed: completedTasks.length}) }}</span>
            </div>
            <div class="task-toolbar-actions">
                <button class="toolbar-button toolbar-button-primary" @click="fileInput.click()">
                    <Heroicon name="PlusIcon" class="w-4 h-4" /> {{ t('addTasksBtn') }}
                </button>
                <button class="toolbar-button" @click="folderInput.click()">
                    <Heroicon name="FolderOpenIcon" class="w-4 h-4" /> {{ t('importFolderBtn') }}
                </button>
                <button class="toolbar-button toolbar-button-success" :disabled="!hasSelectedPendingTasks" @click="runAllPendingTasks(true)">
                    <Heroicon name="PlayIcon" class="w-4 h-4" /> {{ t('startSelected') }}
                </button>
                <button class="toolbar-button" :disabled="!selectedRunning" @click="cancelSelectedTasks">
                    <Heroicon name="StopIcon" class="w-4 h-4" /> {{ t('cancelSelected') }}
                </button>
                <button class="toolbar-button toolbar-button-danger" :disabled="!selectedActive" @click="removeSelectedTasks('active')">
                    <Heroicon name="TrashIcon" class="w-4 h-4" /> {{ t('removeSelected') }}
                </button>
            </div>
        </div>

        <div v-if="dragging" class="task-drop-overlay">
            <Heroicon name="CloudArrowUpIcon" class="w-10 h-10" />
            {{ t('dropFilesHere') }}
        </div>

        <TaskGroup :title="t('activeTasksTitle')" :tasks="activeTasks" group="active" :t="t"
                   :all-selected="allActiveSelected" @toggle-all="setAllSelected('active', $event)">
            <TaskCard v-for="task in activeTasks" :key="task.uiId" :task="task" :t="t"
                      @removeTask="removeTask" @fileSelect="handleTaskFileSelect"
                      @triggerFileInput="triggerFileInput" @copyLog="copyLog"
                      @openPreview="openPreview" @printPdf="printPdf" @toggleTaskState="startTask" />
        </TaskGroup>

        <section class="completed-section">
            <div class="completed-toolbar">
                <h3>{{ t('completedTasksTitle') }} <span>{{ completedTasks.length }}</span></h3>
                <div>
                    <button class="toolbar-button toolbar-button-primary" :disabled="!completedTasks.length || batchDownloadBusy" @click="openBatchDownload">
                        <span v-if="batchDownloadBusy" class="task-spinner"></span>
                        <Heroicon v-else name="ArchiveBoxArrowDownIcon" class="w-4 h-4" /> {{ t('batchDownload') }}
                    </button>
                    <button class="toolbar-button toolbar-button-danger" :disabled="!selectedCompleted" @click="removeSelectedTasks('completed')">
                        <Heroicon name="TrashIcon" class="w-4 h-4" /> {{ t('removeSelected') }}
                    </button>
                    <button class="toolbar-button" :disabled="!completedTasks.length" @click="clearAllTasks('completed')">{{ t('clearCompleted') }}</button>
                </div>
            </div>
            <TaskGroup :tasks="completedTasks" group="completed" :t="t" completed
                       :all-selected="allCompletedSelected" @toggle-all="setAllSelected('completed', $event)">
                <TaskCard v-for="task in completedTasks" :key="task.uiId" :task="task" :t="t" completed
                          @removeTask="removeTask" @fileSelect="handleTaskFileSelect"
                          @triggerFileInput="triggerFileInput" @copyLog="copyLog"
                          @openPreview="openPreview" @printPdf="printPdf" @toggleTaskState="startTask" />
            </TaskGroup>
        </section>

        <Modal v-model="batchDownloadOpen" :title="t('batchDownloadOptionsTitle')" size="md">
            <p class="batch-download-help">{{ t('batchDownloadOptionsHelp') }}</p>
            <div v-if="availableBatchTypes.length" class="batch-format-actions">
                <button type="button" class="batch-format-action" @click="selectedBatchTypes = [...availableBatchTypes]">{{ t('selectAllFormats') }}</button>
                <button type="button" class="batch-format-action" @click="selectedBatchTypes = []">{{ t('clearFormatSelection') }}</button>
            </div>
            <div v-if="availableBatchTypes.length" class="batch-format-list">
                <label v-for="fileType in availableBatchTypes" :key="fileType" class="batch-format-option"
                       :class="{'batch-format-option-selected': selectedBatchTypes.includes(fileType)}">
                    <input type="checkbox" :value="fileType" v-model="selectedBatchTypes">
                    <span>{{ formatTypeLabel(fileType) }}</span>
                </label>
            </div>
            <div v-else-if="!hasBatchAttachments" class="batch-download-empty">{{ t('noBatchFormatsAvailable') }}</div>
            <label v-if="hasBatchAttachments" class="batch-format-option batch-attachment-option">
                <input type="checkbox" v-model="includeBatchAttachments">
                <span>{{ t('includeAttachments') }}</span>
            </label>
            <div v-if="!canConfirmBatchDownload" class="batch-download-warning">{{ t('selectAtLeastOneFormat') }}</div>
            <template #footer>
                <div class="batch-download-footer">
                    <button class="toolbar-button" @click="batchDownloadOpen = false">{{ t('cancelBtn') }}</button>
                    <button class="toolbar-button toolbar-button-primary" :disabled="!canConfirmBatchDownload || batchDownloadBusy" @click="confirmBatchDownload">
                        <span v-if="batchDownloadBusy" class="task-spinner"></span>
                        <Heroicon v-else name="ArchiveBoxArrowDownIcon" class="w-4 h-4" />
                        {{ t('downloadSelectedFormats') }}
                    </button>
                </div>
            </template>
        </Modal>
    </main>
</template>

<script setup>
import { computed, inject, ref } from 'vue';
import TaskCard from './TaskCard.vue';
import TaskGroup from './TaskGroup.vue';
import Heroicon from '../ui/Heroicon.vue';
import Modal from '../ui/Modal.vue';

const props = defineProps({t: Function});
const activeTasks = inject('activeTasks');
const completedTasks = inject('completedTasks');
const hasSelectedPendingTasks = inject('hasSelectedPendingTasks');
const hasSelectedCompletedTasks = inject('hasSelectedCompletedTasks');
const batchDownloadBusy = inject('batchDownloadBusy');
const errors = inject('errors');
const removeTask = inject('removeTask');
const clearAllTasks = inject('clearAllTasks');
const handleTaskFileSelect = inject('handleTaskFileSelect');
const handleFilesSelect = inject('handleFilesSelect');
const handleFolderSelect = inject('handleFolderSelect');
const triggerFileInput = inject('triggerFileInput');
const runAllPendingTasks = inject('runAllPendingTasks');
const toggleTaskState = inject('toggleTaskState');
const copyLog = inject('copyLog');
const openPreview = inject('openPreview');
const printPdf = inject('printPdf');
const setAllSelected = inject('setAllSelected');
const removeSelectedTasks = inject('removeSelectedTasks');
const cancelSelectedTasks = inject('cancelSelectedTasks');
const prepareBatchDownload = inject('prepareBatchDownload');
const downloadSelectedTasks = inject('downloadSelectedTasks');

const fileInput = ref(null);
const folderInput = ref(null);
const dragging = ref(false);
const batchDownloadOpen = ref(false);
const selectedBatchTypes = ref([]);
const includeBatchAttachments = ref(true);
const selectedActive = computed(() => activeTasks.value.some(task => task.selected));
const selectedRunning = computed(() => activeTasks.value.some(task => task.selected && task.isTranslating));
const selectedCompleted = computed(() => completedTasks.value.some(task => task.selected));
const allActiveSelected = computed(() => activeTasks.value.length > 0 && activeTasks.value.every(task => task.selected));
const allCompletedSelected = computed(() => completedTasks.value.length > 0 && completedTasks.value.every(task => task.selected));
const selectedCompletedTasks = computed(() => completedTasks.value.filter(task => task.selected));
const availableBatchTypes = computed(() => [...new Set(
    selectedCompletedTasks.value.flatMap(task => Object.keys(task.downloads || {}))
)].sort());
const hasBatchAttachments = computed(() => selectedCompletedTasks.value.some(
    task => task.attachment && Object.keys(task.attachment).length > 0
));
const canConfirmBatchDownload = computed(() =>
    selectedBatchTypes.value.length > 0 || (hasBatchAttachments.value && includeBatchAttachments.value)
);
const startTask = task => toggleTaskState(task, errors);
const onDrop = event => {
    dragging.value = false;
    handleFilesSelect(event);
};
const openBatchDownload = async () => {
    if (!selectedCompletedTasks.value.length) setAllSelected('completed', true);
    const options = await prepareBatchDownload();
    if (!options) return;
    selectedBatchTypes.value = [...options.fileTypes];
    includeBatchAttachments.value = options.hasAttachments;
    batchDownloadOpen.value = true;
};
const formatTypeLabel = fileType => {
    if (fileType === 'markdown_zip') return props.t('downloadMdZip');
    if (fileType === 'markdown') return props.t('downloadMdEmbedded');
    return fileType.toUpperCase();
};
const confirmBatchDownload = async () => {
    const downloaded = await downloadSelectedTasks({
        fileTypes: [...selectedBatchTypes.value],
        includeAttachments: includeBatchAttachments.value,
    });
    if (downloaded) batchDownloadOpen.value = false;
};
</script>
