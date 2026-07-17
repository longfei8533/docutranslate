<template>
    <section class="quick-settings">
        <div class="quick-setting-field">
            <label>{{ t('targetLanguageLabel') }}</label>
            <select v-model="form.to_lang" @change="saveSetting('translator_to_lang', form.to_lang)">
                <option value="Simplified Chinese">中文(简体中文)</option>
                <option value="English">English</option>
                <option value="Traditional Chinese">中文(繁體中文)</option>
                <option value="Spanish">Español</option>
                <option value="French">Français</option>
                <option value="German">Deutsch</option>
                <option value="Japanese">日本語</option>
                <option value="Korean">한국어</option>
                <option value="Russian">Русский</option>
                <option value="Portuguese">Português</option>
                <option value="Arabic">العَرَبِيَّة</option>
                <option value="Vietnamese">Tiếng Việt</option>
                <option value="custom">{{ t('targetLanguageCustom') }}</option>
            </select>
            <input v-if="form.to_lang === 'custom'" v-model="form.custom_to_lang"
                   :class="{'quick-input-error': errors.custom_to_lang}"
                   @change="saveSetting('translator_custom_to_lang', form.custom_to_lang); clearError('custom_to_lang')"
                   :placeholder="t('customLangPlaceholder')">
        </div>

        <div class="quick-setting-field quick-prompt">
            <label>{{ t('customPromptLabel') }}</label>
            <textarea v-model="form.custom_prompt" rows="2"
                      @change="saveSetting('custom_prompt', form.custom_prompt)"
                      :placeholder="t('customPromptPlaceholder')"></textarea>
        </div>

        <div class="quick-setting-field quick-glossary">
            <label>{{ t('glossaryLabel') }}</label>
            <input ref="glossaryInput" type="file" multiple accept=".csv" class="hidden"
                   @change="handleGlossaryFiles">
            <div class="quick-glossary-actions">
                <button type="button" class="quick-button" @click="glossaryInput.click()">
                    <Heroicon name="ArrowUpTrayIcon" class="w-4 h-4" />
                    {{ t('glossaryChooseFiles') }}
                </button>
                <button type="button" class="quick-button" @click="openGlossaryModal">
                    <Heroicon name="ClipboardDocumentListIcon" class="w-4 h-4" />
                    {{ t('viewGlossaryBtn') }} ({{ glossaryCount }})
                </button>
                <button v-if="glossaryCount" type="button" class="quick-icon-button text-danger"
                        :title="t('clearGlossaryBtn')" @click="clearGlossary">
                    <Heroicon name="TrashIcon" class="w-4 h-4" />
                </button>
            </div>
            <span class="quick-help">{{ glossaryCount ? t('glossaryLoadedCount', { count: glossaryCount }) : t('glossaryHelpShort') }}</span>
        </div>
    </section>
</template>

<script setup>
import { inject, ref } from 'vue';
import Heroicon from '../ui/Heroicon.vue';

defineProps({ t: Function });
const form = inject('form');
const errors = inject('errors');
const glossaryCount = inject('glossaryCount');
const saveSetting = inject('saveSetting');
const clearError = inject('clearError');
const handleGlossaryFiles = inject('handleGlossaryFiles');
const clearGlossary = inject('clearGlossary');
const openGlossaryModal = inject('openGlossaryModal');
const glossaryInput = ref(null);
</script>
