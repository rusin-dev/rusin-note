(function () {
    'use strict';

    var mount = document.getElementById('richTextEditor');
    var textarea = document.getElementById('noteContent');
    var form = document.getElementById('noteForm');
    var toggle = document.getElementById('editorModeToggle');
    if (!mount || !textarea || !form || !toggle) return;

    var config = window.RUSIN_EDITOR_CONFIG || {};
    var labels = config.l10n || {};
    var editor = null;
    var enhanced = false;
    var mode = 'source';

    function notify(value) {
        textarea.value = value;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function isRich() {
        return enhanced && mode === 'rich';
    }

    function sync() {
        if (isRich()) textarea.value = editor.getValue();
        return textarea.value;
    }

    function insertSource(value) {
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        textarea.value = textarea.value.slice(0, start) + value + textarea.value.slice(end);
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = start + value.length;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insertValue(value) {
        if (isRich()) {
            editor.insertMD(value);
            notify(editor.getValue());
        } else {
            insertSource(value);
        }
    }

    function updateModeUI() {
        form.classList.toggle('source-mode', mode === 'source');
        form.dataset.editorMode = mode;
        toggle.textContent = mode === 'rich' ? labels.sourceMode : labels.richMode;
        toggle.setAttribute('aria-pressed', mode === 'source' ? 'true' : 'false');
    }

    function setMode(next) {
        if (!enhanced || next === mode) return;
        if (next === 'source') {
            sync();
            mode = 'source';
            updateModeUI();
            textarea.focus();
        } else {
            editor.setValue(textarea.value, true);
            mode = 'rich';
            updateModeUI();
            editor.focus();
        }
    }

    function escapeHTML(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    window.RusinMarkdownEditor = {
        getValue: sync,
        setValue: function (value) {
            if (isRich()) {
                editor.setValue(value, true);
                notify(editor.getValue());
            } else {
                notify(value);
            }
        },
        insertValue: insertValue,
        isRich: isRich,
        sync: sync,
        toggleMode: function () { setMode(mode === 'rich' ? 'source' : 'rich'); },
        focus: function () {
            if (isRich()) editor.focus();
            else textarea.focus();
        }
    };

    toggle.addEventListener('click', function () {
        window.RusinMarkdownEditor.toggleMode();
    });

    if (!window.Vditor) return;

    var toolbar = [
        'headings', 'bold', 'italic', 'strike', 'inline-code', '|',
        'quote', 'list', 'ordered-list', 'check', 'line', '|',
        'code', 'table', 'link'
    ];
    if (config.imagesApi) toolbar.push('upload');
    toolbar.push('|', 'undo', 'redo', '|', 'outline', 'fullscreen');

    var hintExtensions = [];
    if (config.noteRefs && config.noteRefs.api) {
        hintExtensions.push({
            key: '#',
            hint: function (query) {
                return fetch(config.noteRefs.api + '?q=' + encodeURIComponent(query || ''), {
                    headers: { 'Accept': 'application/json' }
                }).then(function (response) {
                    if (!response.ok) return [];
                    return response.json();
                }).then(function (data) {
                    return ((data && data.items) || []).map(function (item) {
                        return {
                            value: '#' + item.id + ' ',
                            html: '<div class="editor-ref-item"><span class="editor-ref-id">#' +
                                escapeHTML(item.id) + '</span><span class="editor-ref-title">' +
                                escapeHTML(item.title || '') + '</span></div>'
                        };
                    });
                }).catch(function () { return []; });
            }
        });
    }

    var options = {
        cdn: config.assetBase,
        mode: 'wysiwyg',
        value: textarea.value,
        height: '100%',
        minHeight: 240,
        placeholder: config.placeholder || '',
        lang: config.lang === 'en' ? 'en_US' : 'zh_CN',
        icon: 'ant',
        cache: { enable: false },
        toolbar: toolbar,
        toolbarConfig: { pin: true },
        fullscreen: { index: 40 },
        outline: { enable: false, position: 'right' },
        preview: {
            cdn: config.assetBase,
            emojiPath: config.assetBase + '/dist/images/emoji',
            markdown: {
                sanitize: true,
                callout: true,
                codeBlockPreview: true,
                mathBlockPreview: true
            },
            math: { engine: 'KaTeX' },
            hljs: { enable: true, lineNumber: true, style: 'github' },
            theme: {
                current: 'light',
                path: config.assetBase + '/dist/css/content-theme'
            }
        },
        hint: {
            emojiPath: config.assetBase + '/dist/images/emoji',
            extend: hintExtensions
        },
        input: notify,
        after: function () {
            enhanced = true;
            mode = 'rich';
            form.classList.add('editor-enhanced');
            toggle.hidden = false;
            textarea.value = editor.getValue();
            updateModeUI();
        }
    };

    if (config.imagesApi) {
        options.upload = {
            accept: 'image/*',
            multiple: false,
            handler: function (files) {
                if (typeof window.RusinNoteUploadImage !== 'function') return null;
                return Promise.all(Array.from(files).map(function (file) {
                    return window.RusinNoteUploadImage(file);
                })).then(function () { return null; }).catch(function (error) {
                    return error && error.message ? error.message : String(error);
                });
            }
        };
    }

    editor = new window.Vditor(mount, options);
})();
