#!/usr/bin/env node
/**
 * Defuddle extraction wrapper for doc-indexer.
 *
 * Reads a saved HTML file and extracts main content using Defuddle,
 * which provides multi-pass content detection with code block
 * standardization (language detection, line number removal,
 * toolbar/header removal).
 *
 * Usage: node defuddle_extract.mjs <html-file-path> [source-url]
 * Output: JSON to stdout with {title, content, wordCount}
 * Exit 0 on success, 1 on failure.
 */

import { Defuddle } from 'defuddle/node';
import { readFileSync } from 'fs';

const htmlPath = process.argv[2];
const url = process.argv[3] || '';

if (!htmlPath) {
    process.stderr.write('Usage: node defuddle_extract.mjs <html-file> [url]\n');
    process.exit(1);
}

const MIN_CONTENT_LENGTH = 200;

const OPTION_PASSES = [
    { markdown: true },
    { markdown: true, removeLowScoring: false },
    { markdown: true, removeLowScoring: false, removeHiddenElements: false },
];

try {
    const html = readFileSync(htmlPath, 'utf-8');
    let best = null;

    for (const opts of OPTION_PASSES) {
        const result = await Defuddle(html, url, opts);
        if (!best || (result.content || '').length > (best.content || '').length) {
            best = result;
        }
        if ((result.content || '').length >= MIN_CONTENT_LENGTH) break;
    }

    process.stdout.write(JSON.stringify({
        title: best.title || '',
        content: best.content || '',
        wordCount: best.wordCount || 0,
    }));
} catch (err) {
    process.stderr.write(`Defuddle error: ${err.message}\n`);
    process.exit(1);
}
