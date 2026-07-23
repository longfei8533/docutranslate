import { ref } from 'vue';

const SUPPORTED_LANGUAGES = ['zh', 'en'];

export function useI18n() {
    const savedLanguage = localStorage.getItem('ui_language');
    const initialLanguage = SUPPORTED_LANGUAGES.includes(savedLanguage) ? savedLanguage : 'zh';
    const currentLang = ref(initialLanguage);
    const i18nData = ref({});

    if (savedLanguage !== initialLanguage) {
        localStorage.setItem('ui_language', initialLanguage);
    }

    const t = (k, params) => {
        let v = i18nData.value[k] || k;
        if (params) {
            for (const [key, val] of Object.entries(params)) {
                v = v.replace(new RegExp(`\\{${key}\\}`, 'g'), String(val));
            }
        }
        return v;
    };

    const setLanguage = async (l) => {
        if (!SUPPORTED_LANGUAGES.includes(l)) return;

        currentLang.value = l;
        localStorage.setItem('ui_language', l);
        document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en';
        // Reload i18n data
        try {
            const res = await fetch(`/static/i18n/${l}.json`);
            i18nData.value = await res.json();
        } catch (e) {
            console.error('Failed to load i18n:', e);
        }
    };

    const loadI18n = async () => {
        try {
            const lang = currentLang.value || 'zh';
            const res = await fetch(`/static/i18n/${lang}.json`);
            i18nData.value = await res.json();
        } catch (e) {
            // Fallback defaults
            i18nData.value = {
                pageTitle: "DocuTranslate",
                tutorialBtn: "教程",
                workflowTitle: "选择工作流",
                autoWorkflowLabel: "自动选择工作流",
                workflowOptionPptx: "PPTX 演示文稿",
                pptxSettingsTitleText: "PPTX 设置",
                mineruDeployServerUrlLabel: "Server URL",
                mineruDeployLangListLabel: "语言列表 (Pipeline模式)",
                mineruDeployServerUrlPlaceholder: "http://127.0.0.1:30000",
                mineruDeployParseMethodLabel: "解析方法 (Parse Method)",
                mineruDeployTableEnableLabel: "表格识别 (Table Recognition)"
            };
        }
    };

    return {
        currentLang,
        i18nData,
        t,
        setLanguage,
        loadI18n
    };
}
