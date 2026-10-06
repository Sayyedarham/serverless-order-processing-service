import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_rate: {
      executor: 'constant-arrival-rate',
      rate: 5, // 5 requests per second (respects API Gateway safety throttle)
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 10,
      maxVUs: 20,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'], // < 1% errors
    http_req_duration: ['p(95)<1000', 'p(99)<2000'], // 95% < 1s, 99% < 2s
  },
};

const BASE_URL = __ENV.API_URL || 'https://l67j9sjm76.execute-api.us-east-1.amazonaws.com';

export default function () {
  const timestamp = Date.now();
  const vu = __VU;
  const iter = __ITER;
  const idempotencyKey = `k6-${vu}-${iter}-${timestamp}-${Math.random().toString(36).substring(7)}`;

  const payload = JSON.stringify({
    customer_id: `cust-k6-${vu}`,
    items: [
      {
        item_id: 'item-k6-alpha',
        name: 'High Performance SSD',
        quantity: 1,
        price: 89.99,
      },
      {
        item_id: 'item-k6-beta',
        name: 'Cat6 Ethernet Cable',
        quantity: 2,
        price: 7.50,
      },
    ],
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
  };

  const res = http.post(`${BASE_URL}/orders`, payload, params);

  check(res, {
    'status is 202': (r) => r.status === 202,
    'has orderId': (r) => {
      try {
        const json = JSON.parse(r.body);
        return json.orderId !== undefined;
      } catch (e) {
        return false;
      }
    },
  });

  sleep(0.1);
}
