"""Shared constants used by multiple scripts (crawl, extract)."""

# JavaScript injected into the live page to clean code blocks before HTML extraction.
# Uses computed styles (not class names) to generically catch noise from any syntax
# highlighting library -- Torchlight, Prism, highlight.js, Shiki, Pygments, etc.
#
# Three cleaning passes:
# 1. Remove invisible/decorative elements inside <pre> (line numbers, copy targets,
#    annotation anchors) detected via computed CSS: display:none, visibility:hidden,
#    user-select:none, or aria-hidden="true".
# 2. Unwrap div-per-line wrappers (Torchlight, Docusaurus) that cause markdownify to
#    emit double blank lines between every line of code. Only triggers when ALL direct
#    children of <code> are <div> elements -- a clear div-per-line structure.
# 3. Expand <details> elements so collapsed content is visible.
JS_CLEAN_CODE_BLOCKS = """
(() => {
    // Pass 1: Remove hidden/decorative elements inside <pre>
    document.querySelectorAll('pre').forEach(pre => {
        pre.querySelectorAll('*').forEach(el => {
            const s = window.getComputedStyle(el);
            if (s.display === 'none' ||
                s.visibility === 'hidden' ||
                s.userSelect === 'none' ||
                el.getAttribute('aria-hidden') === 'true') {
                el.remove();
            }
        });
    });
    // Pass 2: Unwrap div-per-line wrappers inside <code>
    document.querySelectorAll('pre code').forEach(code => {
        const ch = [...code.children];
        if (ch.length > 0 && ch.every(c => c.tagName === 'DIV')) {
            ch.forEach(div => {
                while (div.firstChild) code.insertBefore(div.firstChild, div);
                code.insertBefore(document.createTextNode('\\n'), div);
                div.remove();
            });
        }
    });
    // Pass 3: Expand <details> elements
    document.querySelectorAll('details').forEach(d => d.open = true);
})()
"""
