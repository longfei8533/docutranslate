<template>
    <section class="task-group">
        <div v-if="title" class="task-group-title"><h3>{{ title }}</h3><span>{{ tasks.length }}</span></div>
        <div class="task-table-header">
            <div><input type="checkbox" :checked="allSelected" @change="$emit('toggle-all', $event.target.checked)"></div>
            <div>{{ t('fileColumn') }}</div>
            <div>{{ t('statusColumn') }}</div>
            <div>{{ t('progressColumn') }}</div>
            <div class="task-optional-rate">{{ t('successRateColumn') }}</div>
            <div class="task-optional-duration">{{ t('durationColumn') }}</div>
            <div class="text-right">{{ t('actionsColumn') }}</div>
        </div>
        <div v-if="!tasks.length" class="task-empty">
            <Heroicon :name="completed ? 'CheckCircleIcon' : 'InboxIcon'" class="w-8 h-8" />
            <span>{{ completed ? t('noCompletedTasks') : t('noActiveTasks') }}</span>
        </div>
        <slot></slot>
    </section>
</template>

<script setup>
import Heroicon from '../ui/Heroicon.vue';
defineProps({title: String, tasks: Array, group: String, t: Function, completed: Boolean, allSelected: Boolean});
defineEmits(['toggle-all']);
</script>
