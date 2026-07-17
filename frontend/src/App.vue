<template>
<div id="app-root">
    <div class="main-container">
        <header class="app-header">
            <div class="app-brand">
                <img src="/static/favicon.ico" alt="DocuTranslate">
                <div>
                    <h1>DocuTranslate</h1>
                    <span>{{ t('appSubtitle') }}</span>
                </div>
            </div>
            <div class="app-header-actions">
                <button class="header-button" @click="tutorialOpen = true">
                    <Heroicon name="QuestionMarkCircleIcon" class="w-5 h-5" /> {{ t('tutorialBtn') }}
                </button>
                <button class="header-button header-settings-button" @click="settingsOpen = true">
                    <Heroicon name="Cog6ToothIcon" class="w-5 h-5" /> {{ t('settingsBtn') }}
                </button>
            </div>
        </header>

        <div class="app-workspace">
            <aside class="quick-settings-column">
                <QuickSettings :t="t" />
            </aside>
            <div class="task-manager-column">
                <TaskArea :t="t" />
            </div>
        </div>
    </div>

    <!-- Modals -->
    <GlossaryModal ref="glossaryModalRefLocal" :t="t" />
    <ContributorsModal :t="t" />
    <Modal v-model="settingsOpen" :title="t('settingsModalTitle')" size="xl" :close-on-backdrop="false">
        <SettingsPanel
            :t="t"
            :enginList="enginList"
            :showMineruToken="showMineruToken"
            :showIdentityOption="showIdentityOption"
            @update:showMineruToken="val => showMineruToken = val" />
        <template #footer>
            <button class="toolbar-button toolbar-button-primary" @click="settingsOpen = false">{{ t('closeBtn') }}</button>
        </template>
    </Modal>
    <Modal v-model="tutorialOpen" :title="t('tutorialModalTitle')" size="xl">
        <TutorialContent :t="t" @close="tutorialOpen = false" />
    </Modal>

    <!-- Preview Offcanvas -->
    <PreviewOffcanvas
        ref="previewOffcanvasRef"
        :t="t" />

    <!-- Bottom Controls -->
    <BottomControls
        :currentLang="currentLang"
        @setLang="setLanguage"
        @setTheme="setTheme" />
</div>
</template>

<script setup>
import { ref, onMounted, provide, watch } from 'vue';
import TutorialContent from './components/modals/TutorialContent.vue';
import ContributorsModal from './components/modals/ContributorsModal.vue';
import GlossaryModal from './components/modals/GlossaryModal.vue';
import SettingsPanel from './components/settings/SettingsPanel.vue';
import QuickSettings from './components/settings/QuickSettings.vue';
import TaskArea from './components/tasks/TaskArea.vue';
import PreviewOffcanvas from './components/preview/PreviewOffcanvas.vue';
import BottomControls from './components/layout/BottomControls.vue';
import Modal from './components/ui/Modal.vue';
import Heroicon from './components/ui/Heroicon.vue';

// Import composables
import { useSettings } from './composables/useSettings.js';
import { useI18n } from './composables/useI18n.js';
import { useGlossary } from './composables/useGlossary.js';
import { useTasks } from './composables/useTasks.js';
import { usePreview } from './composables/usePreview.js';

// ===== Initialize Composables =====
const settings = useSettings();
const i18n = useI18n();
const glossary = useGlossary();
const tasksComposable = useTasks(settings, glossary, i18n);
const preview = usePreview(i18n);

// Destructure from composables
const { form, workflowParams, errors, defaultParams, default_workflows, queue_concurrent, webSkipValidation, envForceOverride,
        clearError, loadConfig, saveSetting, saveSettingArray, saveWorkflowParam,
        saveAllSettings, setupPlatformWatchers, exportConfig, importConfig,
        saveDefaultWorkflows } = settings;

const { currentLang, t, setLanguage, loadI18n } = i18n;

const { glossaryData, glossaryCount, glossaryModalRef, handleGlossaryFiles, clearGlossary,
        openGlossaryModal, downloadGlossaryTemplate } = glossary;

const { tasks, activeTasks, completedTasks, hasPendingTasks, hasSelectedPendingTasks,
        hasSelectedCompletedTasks, batchDownloadBusy, createNewTask, removeTask, clearAllTasks,
        handleTaskFileSelect, handleTaskFileDrop, handleFilesSelect, triggerFileInput, selectTaskWorkflow,
        handleFolderSelect, runAllPendingTasks, toggleTaskState, copyLog,
        setAllSelected, removeSelectedTasks, cancelSelectedTasks, prepareBatchDownload,
        downloadSelectedTasks } = tasksComposable;

const { previewMode, syncScrollEnabled, previewTask, isOpen, previewOffcanvasComponent,
        openPreview, closePreview, setPreviewMode, toggleSyncScroll, printPdf, initSplit } = preview;

// Local ref for template binding, sync to composable
const previewOffcanvasRef = ref(null);
watch(previewOffcanvasRef, (val) => {
    previewOffcanvasComponent.value = val;
}, { immediate: true });

// Sync glossaryModalRef to composable
const glossaryModalRefLocal = ref(null);
watch(glossaryModalRefLocal, (val) => {
    glossaryModalRef.value = val;
}, { immediate: true });

// ===== Provide to child components =====
provide('form', form);
provide('workflowParams', workflowParams);
provide('errors', errors);
provide('defaultParams', defaultParams);
provide('default_workflows', default_workflows);
provide('queue_concurrent', queue_concurrent);
provide('webSkipValidation', webSkipValidation);
provide('envForceOverride', envForceOverride);
provide('glossaryData', glossaryData);
provide('glossaryCount', glossaryCount);
provide('tasks', tasks);
provide('activeTasks', activeTasks);
provide('completedTasks', completedTasks);
provide('hasPendingTasks', hasPendingTasks);
provide('hasSelectedPendingTasks', hasSelectedPendingTasks);
provide('hasSelectedCompletedTasks', hasSelectedCompletedTasks);
provide('batchDownloadBusy', batchDownloadBusy);
provide('previewMode', previewMode);
provide('syncScrollEnabled', syncScrollEnabled);
provide('previewTask', previewTask);
provide('previewIsOpen', isOpen);
provide('initSplit', initSplit);

// Provide methods
provide('clearError', clearError);
provide('saveSetting', saveSetting);
provide('saveSettingArray', saveSettingArray);
provide('saveWorkflowParam', saveWorkflowParam);
provide('saveAllSettings', saveAllSettings);
provide('handleGlossaryFiles', handleGlossaryFiles);
provide('clearGlossary', clearGlossary);
provide('openGlossaryModal', openGlossaryModal);
provide('downloadGlossaryTemplate', downloadGlossaryTemplate);
provide('exportConfig', exportConfig);
provide('importConfig', importConfig);
provide('setPreviewMode', setPreviewMode);
provide('toggleSyncScroll', toggleSyncScroll);
provide('printPdf', printPdf);
provide('createNewTask', createNewTask);
provide('removeTask', removeTask);
provide('clearAllTasks', clearAllTasks);
provide('handleTaskFileSelect', handleTaskFileSelect);
provide('handleTaskFileDrop', handleTaskFileDrop);
provide('handleFilesSelect', handleFilesSelect);
provide('triggerFileInput', triggerFileInput);
provide('selectTaskWorkflow', selectTaskWorkflow);
provide('handleFolderSelect', handleFolderSelect);
provide('runAllPendingTasks', runAllPendingTasks);
provide('toggleTaskState', toggleTaskState);
provide('copyLog', copyLog);
provide('setAllSelected', setAllSelected);
provide('removeSelectedTasks', removeSelectedTasks);
provide('cancelSelectedTasks', cancelSelectedTasks);
provide('prepareBatchDownload', prepareBatchDownload);
provide('downloadSelectedTasks', downloadSelectedTasks);
provide('openPreview', openPreview);
provide('closePreview', closePreview);
provide('saveDefaultWorkflows', saveDefaultWorkflows);

// ===== Local State =====
const enginList = ref([]);
const showMineruToken = ref(false);
const showIdentityOption = ref(true);
const settingsOpen = ref(false);
const tutorialOpen = ref(false);

watch(() => Object.values(errors).some(Boolean), invalid => {
    if (invalid) settingsOpen.value = true;
});

// ===== Computed =====

// ===== Theme =====
const setTheme = (theme) => {
    localStorage.setItem('theme', theme);
    if (theme === 'auto') document.documentElement.setAttribute('data-theme', window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    else document.documentElement.setAttribute('data-theme', theme);
};

// ===== Lifecycle =====
onMounted(async () => {
    // Load i18n
    await loadI18n();

    // Backend Metadata
    try {
        const [enginRes, paramsRes] = await Promise.all([
            fetch('/service/engin-list'), fetch("/service/default-params")
        ]);
        enginList.value = await enginRes.json();
        const paramsData = await paramsRes.json();
        Object.assign(defaultParams, paramsData);
        webSkipValidation.value = paramsData.web_skip_validation ?? false;
        envForceOverride.value = paramsData.env_force_override ?? false;
    } catch (e) {
        console.error("Backend init failed", e);
    }

    loadConfig(defaultParams);
    setupPlatformWatchers();
    setTheme(localStorage.getItem('theme') || 'auto');

    // Restore tasks
    if (window.location.pathname.includes('/admin')) {
        document.title = "DocuTranslate - Admin Panel";
        try {
            const r = await fetch('/service/task-list');
            const ids = await r.json();
            if (ids) ids.reverse().forEach(id => createNewTask(id));
        } catch (e) {}
    } else {
        const savedIds = JSON.parse(localStorage.getItem('active_task_ids') || '[]');
        if (savedIds.length) savedIds.forEach(id => createNewTask(id));
    }

    // Global resize handler for preview
    window.addEventListener('resize', () => {
        if (isOpen.value) {
            initSplit();
        }
    });
});
</script>
