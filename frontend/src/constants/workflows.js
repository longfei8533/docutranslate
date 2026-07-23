// Workflow configurations
export const DEFAULT_WORKFLOW_MAPPING = {
    "translate_only": [".txt", ".md"],
    "parse_only": [".pdf", ".docx", ".pptx", ".html", ".mobi"],
    "md2docx_only": [".md"],
    "full_flow": [".pdf", ".docx", ".pptx", ".html", ".mobi"]
};

export const DEFAULT_EXTENSIONS = {
    "translate_only": [".txt", ".md"],
    "parse_only": [".pdf", ".docx", ".pptx", ".html", ".mobi"],
    "md2docx_only": [".md"],
    "full_flow": [".pdf", ".docx", ".pptx", ".html", ".mobi"]
};

// These workflows remain available to the backend/API, but are intentionally
// unavailable when creating new tasks from the Web UI.
export const WEB_DISABLED_WORKFLOWS = new Set(['srt', 'ass', 'epub']);
export const WEB_DISABLED_EXTENSIONS = new Set(['srt', 'ass', 'epub']);

export const WEB_DEFAULT_WORKFLOW_MAPPING = {
    pdf: 'markdown_based', png: 'markdown_based', jpg: 'markdown_based', jpeg: 'markdown_based',
    gif: 'markdown_based', bmp: 'markdown_based', webp: 'markdown_based',
    txt: 'txt', md: 'markdown_based',
    docx: 'docx', doc: 'docx',
    xlsx: 'xlsx', csv: 'xlsx', xls: 'xlsx',
    pptx: 'pptx', ppt: 'pptx',
    json: 'json', html: 'html', htm: 'html'
};

export const WEB_DEFAULT_EXTENSIONS = Object.keys(WEB_DEFAULT_WORKFLOW_MAPPING);

export const getFileExtension = (filename = '') => {
    const basename = String(filename).split(/[\\/]/).pop() || '';
    const dotIndex = basename.lastIndexOf('.');
    return dotIndex > -1 ? basename.slice(dotIndex + 1).toLowerCase() : '';
};

export const isWebDisabledFile = (file) => WEB_DISABLED_EXTENSIONS.has(
    getFileExtension(typeof file === 'string' ? file : file?.name)
);

export const sanitizeWebWorkflowMappings = (mappings = {}) => Object.fromEntries(
    Object.entries(mappings).filter(([extension, workflow]) => (
        !WEB_DISABLED_EXTENSIONS.has(extension.toLowerCase()) &&
        !WEB_DISABLED_WORKFLOWS.has(workflow)
    ))
);
