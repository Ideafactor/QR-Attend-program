import test from 'node:test';
import assert from 'node:assert/strict';
import {createAttendanceClient, hasQrScanResult} from '../../js/attendance-client/dist/index.js';
import {createSerialFramer} from '../../js/attendance-react-scanner/dist/framing.js';

test('self-service uses host fetch and sends the actual QR generation timestamp',async()=>{
  const requests=[];
  const client=createAttendanceClient({baseUrl:'/clock/',fetcher:async(url)=>{
    requests.push(url);
    return Response.json(url.endsWith('/qr')?{code:'signed',generated_at:'2026-10-01T09:00:30+09:00'}:{result_since:true,latest_scan:{result:'already_in'}});
  }});
  const qr=await client.employee.getQr();
  const status=await client.employee.getStatus(qr.generated_at);
  assert.deepEqual(requests,['/clock/me/qr','/clock/me/status?since=2026-10-01T09%3A00%3A30%2B09%3A00']);
  assert.equal(hasQrScanResult(status),true);
  assert.equal(hasQrScanResult({...status,result_since:false}),false);
  assert.equal(hasQrScanResult({...status,latest_scan:{result:'pending'}}),false);
  assert.equal(hasQrScanResult({...status,latest_scan:{result:'pending',pending_status:'approved_out'}}),true);
});

test('serial framer keeps partial input and rejects oversized frames as a whole',()=>{
  const framer=createSerialFramer(8);
  assert.deepEqual(framer.push('ab').codes,[]);
  assert.deepEqual(framer.push('cd\r').codes,['abcd']);
  assert.deepEqual(framer.push('\nxy\nz').codes,['xy']);
  assert.equal(framer.flush(),'z');
  assert.equal(framer.flush(),null);
  assert.equal(framer.push('123456789suffix').overflowed,true);
  assert.equal(framer.flush(),null);
  assert.deepEqual(framer.push('good\r\n').codes,['good']);
});
