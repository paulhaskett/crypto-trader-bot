/*
 * Shared browser rendering helpers.
 *
 * Dynamic API/database values must be escaped before entering innerHTML. Fixed
 * markup and class names may remain authored HTML; operator-controlled values
 * must not be interpreted as markup or script.
 */
(function () {
    'use strict';

    window.escapeHtml = function escapeHtml(value) {
        const text = String(value ?? '');
        return text.replace(/[&<>"']/g, (character) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[character]));
    };
})();
