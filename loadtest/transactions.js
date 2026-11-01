// Load test for the banking API: 10 minutes of read traffic through the load balancer.
//
// What this file does:
//   Sends GET /version1/transactions with an API key, from 20 simulated users at once,
//   for 10 minutes. It reads only, so it does not change any data.
//
// Run it from the loadtest folder, after setting BASE_URL and API_KEY (see the README steps):
//   k6 run --env BASE_URL=http://... --env API_KEY=... transactions.js

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

export default function () {
  const res = http.get(`${BASE_URL}/version1/transactions?limit=20`, {
    headers: { 'x-api-key': API_KEY },
  });
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(0.5); // a short pause between requests, like a real user
}
