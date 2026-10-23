// Content-only stage switcher: never reads files or sends medical information.
const stages = {
  read: { number: '01', icon: '▤', title: 'It begins with the document.', body: 'The application extracts text from a PDF or uses OCR for scans and images, while retaining page context for extracted rows.', rule: 'RULE / UNREADABLE VALUES MUST NOT BE GUESSED' },
  check: { number: '02', icon: '◈', title: 'The printed range is the reference.', body: 'Deterministic validation compares each extracted value with the range printed on that report. Missing range information means the status stays unknown.', rule: 'RULE / NO SUBSTITUTE GENERIC RANGES' },
  explain: { number: '03', icon: '✳', title: 'Language follows verified facts.', body: 'An optional model adds plain-language context. A contradictory explanation can be discarded rather than overriding the validated status.', rule: 'RULE / EXPLANATION IS NOT A DIAGNOSIS' }
};
for (const button of document.querySelectorAll('[data-stage]')) {
  button.addEventListener('click', () => {
    const stage = stages[button.dataset.stage]; if (!stage) return;
    for (const [id, value] of Object.entries({ 'stage-number': stage.number, 'stage-icon': stage.icon, 'stage-title': stage.title, 'stage-body': stage.body, 'stage-rule': stage.rule })) document.getElementById(id).textContent = value;
    for (const node of document.querySelectorAll('[data-stage]')) node.setAttribute('aria-pressed', String(node === button));
  });
}
