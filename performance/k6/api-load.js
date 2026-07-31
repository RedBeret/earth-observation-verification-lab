// Load profile for the TerraWatch demo-west environment.
//
// Thresholds are not written here. They are read from the versioned
// performance/thresholds.json so that the k6 run and the Python gate in
// terractl/performance.py cannot drift apart.

import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const config = JSON.parse(open('../thresholds.json'));
const limits = config.thresholds;
const load = config.load;

const INGEST_URL = __ENV.TERRAWATCH_INGEST_URL || 'http://127.0.0.1:18001';
const EVENT_URL = __ENV.TERRAWATCH_EVENT_URL || 'http://127.0.0.1:18002';
const ANALYSIS_URL = __ENV.TERRAWATCH_ANALYSIS_URL || 'http://127.0.0.1:18003';
const SUMMARY_PATH = __ENV.K6_SUMMARY_PATH || '/artifacts/reports/k6-summary.json';

const healthLatency = new Trend('terrawatch_health_latency', true);
const queryLatency = new Trend('terrawatch_query_latency', true);
const requestErrors = new Rate('terrawatch_request_errors');

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-vus',
      vus: load.virtual_users,
      duration: load.duration,
      gracefulStop: load.graceful_stop,
    },
  },
  thresholds: {
    terrawatch_health_latency: [`p(95)<${limits.health_p95_ms}`],
    terrawatch_query_latency: [`p(95)<${limits.query_p95_ms}`],
    terrawatch_request_errors: [`rate<${limits.max_error_rate}`],
    checks: [`rate>=${limits.min_check_success_rate}`],
  },
};

function measure(response, trend, expectedStatus, name) {
  trend.add(response.timings.duration);
  const ok = check(response, {
    [`${name} returned ${expectedStatus}`]: (r) => r.status === expectedStatus,
  });
  requestErrors.add(!ok);
  return ok;
}

export default function () {
  measure(http.get(`${INGEST_URL}/healthz`), healthLatency, 200, 'ingest health');
  measure(http.get(`${EVENT_URL}/healthz`), healthLatency, 200, 'event health');
  measure(http.get(`${ANALYSIS_URL}/healthz`), healthLatency, 200, 'analysis health');

  measure(
    http.get(`${ANALYSIS_URL}/v1/events?bbox=-121,36,-119,38&page=1&page_size=10`),
    queryLatency,
    200,
    'event search',
  );
  measure(
    http.get(`${ANALYSIS_URL}/v1/scenes?bbox=-121,36,-119,38&page=1&page_size=10`),
    queryLatency,
    200,
    'scene search',
  );
  measure(
    http.get(`${ANALYSIS_URL}/v1/events/EVENT-SYN-ABSENT`),
    queryLatency,
    404,
    'unknown event',
  );
}

export function handleSummary(data) {
  const output = {};
  output[SUMMARY_PATH] = JSON.stringify(data, null, 2);
  output.stdout = `k6 completed ${data.metrics.iterations.values.count} iterations\n`;
  return output;
}
