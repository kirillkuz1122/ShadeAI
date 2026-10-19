import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/api/automation.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { knownRule, knownAutomationPage, knownHintPage } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const row = {id:'aut_'+'a'.repeat(32),source_habit_id:'hbt_'+'b'.repeat(32),name:'Синтетическое предложение',status:'pending',version:1,
  trigger:{type:'presence_transition',entity_id:'binary_sensor.test',kind:'arrival_home',from_state:'off',to_state:'on',day_group:'weekdays',timezone:'Asia/Yekaterinburg',window_start:'17:15',window_end:'18:45',wraps_midnight:false},
  action:null,evidence:{support_days:12,eligible_days:15,dispersion_minutes:5},confidence:0.8,source_current:true,approval_valid:false,enabled:false,executable:false,executor_status:'not_implemented',created_at:'2026-10-19T00:00:00Z',updated_at:'2026-10-19T00:00:00Z'};
assert(knownRule(row));
for (const wrong of [null,[],{}, {...row,version:true},{...row,confidence:NaN}, {...row,status:'private-status'},
  {...row,trigger:{...row.trigger,type:'notification'}},{...row,trigger:{...row.trigger,to_state:'off'}},
  {...row,trigger:{...row.trigger,window_start:'24:00'}},{...row,trigger:{...row.trigger,timezone:'private-zone'}},
  {...row,action:{entity_id:'lock.private',service:'turn_on',params:{}}},
  {...row,action:{entity_id:'light.test',service:'turn_off',params:{}}},
  {...row,action:{entity_id:'light.test',service:'turn_on',params:{brightness:255}}},
  {...row,evidence:{...row.evidence,support_days:16}}, {...row,evidence:{...row.evidence,eligible_days:0}},
]) assert(!knownRule(wrong));
assert(knownAutomationPage({automations:[row],total:1,allowed_targets:['light.test']}));
assert(!knownAutomationPage({automations:[],total:0,allowed_targets:['lock.test']}));
assert(!knownAutomationPage({automations:[],total:-1,allowed_targets:[]}));
const hints={feed_id:'11111111-1111-4111-8111-111111111111',latest_id:1,next_id:1,hints:[{id:1,kind:'arrival_delivery',notification_id:1,created_at:'2026-10-19T00:00:00Z'}]};
assert(knownHintPage(hints));
assert(!knownHintPage({...hints,hints:[null]}));
assert(!knownHintPage({...hints,next_id:NaN}));
assert(!knownHintPage({...hints,hints:[{...hints.hints[0],notification_id:-1}]}));
console.log('PASS: bounded proposals/targets/known actions and conditions; safe local hint feed');
