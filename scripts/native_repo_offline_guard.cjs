// Isolated upstream tests only. Never generate signatures or contact Hongguo.
// Upstream collector/test files remain unmodified. Dependency doubles below
// make this a parser/control-flow test, NOT an end-to-end collection test.
'use strict';
const Module = require('node:module');
const originalLoad = Module._load;
const counts = { blockedNetworkCalls: 0, signingPlaceholders: 0, actualSignatures: 0, deviceRegistrations: 0 };
function noNetwork() { counts.blockedNetworkCalls++; throw new Error('OFFLINE_TEST_NETWORK_DISABLED'); }
globalThis.fetch = noNetwork;
for (const id of ['node:http', 'node:https']) {
  const mod = require(id); mod.request = noNetwork; mod.get = noNetwork;
}
const net = require('node:net');
net.connect = noNetwork; net.createConnection = noNetwork; net.Socket.prototype.connect = noNetwork;
Module._load = function (request, parent, isMain) {
  if (parent?.filename?.endsWith('/native/danmaku.js')) {
    if (request === 'axios') return { post: noNetwork };
    if (request === './danmaku-sign') return {
      NONCE_BYTES: 11,
      buildQuery: () => 'offline_fixture_only=true',
      signCommentHeaders: () => { counts.signingPlaceholders++; return {}; },
      newDeviceId: () => { throw new Error('OFFLINE_TEST_IDENTITY_GENERATION_DISABLED'); }
    };
    if (request === './playback-device') return { getPlaybackDevice: noNetwork };
    if (request === './app-source') return { requestJson: noNetwork };
  }
  return originalLoad.call(this, request, parent, isMain);
};
process.on('exit', () => process.stdout.write('OFFLINE_GUARD ' + JSON.stringify(counts) + '\n'));
