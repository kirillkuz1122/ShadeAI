import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/api/processing.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { readProcessing, extractionTime, processingError } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const good = {
  processor: 'llm', llm: true, schema_version: 1, action_authorized: false,
  category: 'reminder', priority: 'default', intent: 'reminder',
  entities: { subject: 'Полить цветы', location: null, service: null },
  time: { source: 'завтра в 07:00', timezone: 'Asia/Yekaterinburg',
    at: '2026-10-19T02:00:00Z', date: null, resolution: 'exact' },
};
assert.equal(readProcessing(good).kind, 'llm');
assert.match(extractionTime(good.time), /07:00:00/);
for (const malformed of [null, [], 'raw secret', { schema_version: 2 },
  { ...good, schema_version: 2 }, { ...good, action_authorized: true },
  { ...good, intent: 'delivery_event' }, { ...good, category: 'toString' },
  { ...good, entities: { ...good.entities, subject: 123 } },
  { ...good, time: { ...good.time, timezone: 'secret-invalid-zone' } },
  { ...good, time: { ...good.time, at: '2026-02-30T02:00:00Z' } },
  { ...good, time: { ...good.time, at: '2026-10-19T24:00:00Z' } },
  { ...good, time: { ...good.time, resolution: 'unresolved' } },
]) {
  assert.notEqual(readProcessing(malformed).kind, 'llm');
}
assert.equal(readProcessing({ processor: 'diagnostic', llm: false }).kind, 'diagnostic');
assert.equal(readProcessing({ processor: 'diagnostic', llm: true }).kind, 'unsupported');
const dateOnly = { ...good.time, source: 'завтра', at: null, date: '2026-10-19', resolution: 'date_only' };
assert.equal(readProcessing({ ...good, time: dateOnly }).kind, 'llm');
assert.equal(extractionTime(dateOnly), '19.10.2026 · время не указано');
assert.equal(readProcessing({ ...good, time: { ...dateOnly, date: '2026-02-30' } }).kind, 'unsupported');
assert.equal(readProcessing({ ...good, category: 'noise', intent: 'none', priority: 'low' }).kind, 'unsupported');
assert.equal(processingError('sensitive-code-012345'), 'Не удалось обработать запись');
assert.equal(processingError('toString'), 'Не удалось обработать запись');
assert.match(processingError('LLM_BAD_RESPONSE'), /неподтверждённые/);
console.log('PASS: supported schema, bounded fields, dates/timezone, unsupported versions, safe errors');
