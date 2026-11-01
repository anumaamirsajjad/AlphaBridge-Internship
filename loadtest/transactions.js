// Load test for the banking API: 10 minutes of read traffic through the API gateway.
//
// What this file does:
//   Finds its endpoints from the API's own description (/openapi.json), so no path is typed by hand.
//   Then 20 simulated users at once send GET requests for 10 minutes: the transaction list,
//   and one transaction by ID (the IDs come from that list). It reads only, so it does not change any data.
//
// Run it through run.ps1, which reads BASE_URL from Terraform. API_KEY must be set first.

import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 20,          // 20 simulated users at the same time
  duration: '10m',  // run for 10 minutes
  thresholds: {
    http_req_failed: ['rate<0.01'],     // fewer than 1% of requests may fail
    http_req_duration: ['p(95)<1000'],  // 95% of requests must finish within 1 second
  },
};

const BASE_URL = __ENV.BASE_URL;
const API_KEY = __ENV.API_KEY;
const HEADERS = { headers: { 'x-api-key': API_KEY } };

// Runs once, before the users start. Finds the list and single-item paths in /openapi.json,
// then lists transactions to get real IDs for the single-item route.
export function setup() {
  const spec = http.get(`${BASE_URL}/openapi.json`).json();
  const paths = Object.keys(spec.paths);
  const listPath = paths.find((p) => p.endsWith('/transactions') && spec.paths[p].get);
  const itemPath = paths.find((p) => p.endsWith('/{transaction_id}') && spec.paths[p].get);
  if (!listPath || !itemPath) {
    throw new Error('openapi.json does not describe the transaction routes');
  }

  const listUrl = `${BASE_URL}${listPath}?limit=20`;
  const list = http.get(listUrl, HEADERS).json();
  const ids = list.items.map((t) => t.transaction_id);
  if (ids.length === 0) {
    throw new Error('no transactions found to read');
  }
  return { listUrl, itemUrl: `${BASE_URL}${itemPath}`, ids };
}

export default function (data) {
  const list = http.get(data.listUrl, HEADERS);
  check(list, { 'list status is 200': (r) => r.status === 200 });

  const id = data.ids[Math.floor(Math.random() * data.ids.length)];
  const item = http.get(data.itemUrl.replace('{transaction_id}', id), HEADERS);
  check(item, { 'item status is 200': (r) => r.status === 200 });

  sleep(0.5); // a short pause between requests, like a real user
}
