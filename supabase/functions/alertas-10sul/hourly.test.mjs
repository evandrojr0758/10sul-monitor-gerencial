import assert from 'node:assert/strict';
import {maintenanceSummary, deliveryDue, monitorAlerts, stockAlerts, HOUR} from './rules.mjs';
const now=Date.parse('2026-10-12T11:20:00Z');
const row=(frota,evento,extra={})=>({os_id:frota,frota,evento,modal:'Knnar',unidade:'ARA',status:'Manutenção',...extra});
const cases=[
 row('1','CORRETIVA Ñ PROG.'),row('1','CORRETIVA Ñ PROG.'), // duplicate fleet/OS
 row('2','CORRETIVA N̈ PROG. PNEU'),row('3','SOS PNEU'),
 row('3','SOS ELÉTRICA'),row('4','SOS MECÂNICA'),row('5','SOS (OUTROS)'),
 row('6','ITR'),row('7','REVISÃO 120'),row('8','REVISÃO TRIMESTRAL'),
 row('9','CORRETIVA Ñ PROG.',{status:'Liberado'}),row('10','SOS',{unidade:'MUC'}),
 row('11','SOS',{modal:'Cavalo ASN'}),row('12','ITR',{excluida_asn_em:'2026-10-12T10:00:00Z'}),
 row('13','ITR',{fim_asn:'2026-10-12 08:00:00'}),
 row('14','REVISÃO',{fim_liberacao_10sul:'2026-10-12T10:00:00Z'}),
 row('15','GM'),row('','SOS'),
 row('6','CORRETIVA Ñ PROG.'), // fleet in two groups counted once in total
];
const summary=maintenanceSummary(cases,now);
assert.deepEqual(summary.counts,{cnp:2,pneus:1,sos:3,itr:1,revisao:2});
assert.equal(summary.total,8);
assert.match(summary.body,/Base sincronizada ASN · 08:20/);
assert.equal(summary.key,maintenanceSummary(cases,now+HOUR).key);
assert.deepEqual(maintenanceSummary([],now).counts,{cnp:0,pneus:0,sos:0,itr:0,revisao:0});
assert.equal(maintenanceSummary([],now).total,0);
assert.equal(deliveryDue(summary,null,now),true);
const prior={sent_at:new Date(now).toISOString(),last_attempt_at:new Date(now).toISOString(),attempts:1};
assert.equal(deliveryDue(summary,prior,now+HOUR-1),false);
assert.equal(deliveryDue(summary,prior,now+HOUR),true);
assert.equal(deliveryDue({kind:'rh_advertencia'},prior,now+2*HOUR),false);
assert.equal(deliveryDue({kind:'sos'},prior,now+HOUR),true);
assert.equal(deliveryDue(summary,{...prior,sent_at:null,last_error:'Push HTTP 503'},now+59000),false);
assert.equal(deliveryDue(summary,{...prior,sent_at:null,last_error:'Push HTTP 503'},now+60000),true);
assert.equal(monitorAlerts([row('42','SOS PNEU',{inicio:'2026-10-12 04:00:00'})],now).length,1);
assert.equal(stockAlerts(Date.parse('2026-10-13T11:00:00Z')).length,1);
console.log('PASS: five groups, all SOS, distinct fleets, closed/deleted/non-ARA/cavalos exclusion, zero counts, actual hourly recurrence, retries, existing SOS/RH/stock.');
