# Optionthropic — Options Analytics SaaS Platform

Institutional-grade derivatives analytics for **NIFTY**, **BANKNIFTY**, and **SENSEX**.

## Features

| Module | Description |
|---|---|
| Gamma Wall Detection | Call/put gamma walls computed via OI-weighted proximity model |
| Max Pain | Per-expiry max-pain strike via OI-weighted loss minimisation |
| Liquidity Trap | OI-to-volume concentration detection near spot |
| Positioning Shifts | Intraday long/short buildup/unwind classification |
| Smart Money Flow | SWEEP / BLOCK / UNUSUAL flow classification by premium size |
| AI Market Summary | Plain-language insights via GPT-4o / Claude |
| Alert Engine | Rule-based alerts published to SQS and persisted in RDS |

---

## Quick Start (Local Docker)

```bash
cp .env.example .env
# Edit .env — set DATA_SOURCE, OPENAI_API_KEY etc.

docker compose up --build
```

- Backend API: http://localhost:8000/docs
- Frontend: http://localhost:3000

---

## Project Structure

```
Optionthropic/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app factory + lifespan
│   │   ├── config.py                   # Pydantic settings
│   │   ├── logging_config.py           # Structured JSON logging
│   │   ├── api/
│   │   │   ├── routes.py               # Analytics endpoints
│   │   │   ├── auth_routes.py          # Signup / login / JWT / Cognito
│   │   │   └── admin_routes.py         # Admin stats + health
│   │   ├── analytics/
│   │   │   ├── options_analysis.py     # PCR, support/resistance
│   │   │   ├── gamma_detection.py      # Gamma walls
│   │   │   ├── liquidity_trap_detection.py
│   │   │   ├── positioning_shift.py
│   │   │   ├── max_pain_detection.py
│   │   │   └── options_flow_detection.py
│   │   ├── alerts/
│   │   │   └── alert_engine.py         # Rules + SQS publish
│   │   ├── ai_engine/
│   │   │   └── market_explainer.py     # OpenAI / Anthropic
│   │   ├── data_ingestion/
│   │   │   ├── data_source_router.py   # NSE / Zerodha / Angel
│   │   │   └── options_collector.py    # 60s polling loop
│   │   ├── db/
│   │   │   └── database.py             # SQLAlchemy async engine
│   │   └── models/                     # 11 SQLAlchemy ORM models
│   ├── Dockerfile
│   ├── apprunner.yaml
│   └── requirements.txt
├── frontend/
│   ├── pages/
│   │   ├── index.js                    # Redirect to dashboard / login
│   │   ├── login.js
│   │   ├── signup.js
│   │   ├── dashboard.js                # Main analytics dashboard
│   │   ├── alerts.js
│   │   ├── profile.js
│   │   └── settings.js
│   ├── components/
│   │   ├── Layout.js                   # Shared nav + footer
│   │   ├── OptionsDashboard.js         # KPIs, SR, shifts
│   │   ├── GammaWallChart.js           # Recharts bar chart
│   │   ├── OptionsFlowPanel.js         # Flow table
│   │   ├── AlertsPanel.js              # Live alert feed
│   │   └── MarketSummary.js            # AI insight card
│   ├── lib/
│   │   ├── api.js                      # Axios client
│   │   └── auth.js                     # Token / session helpers
│   ├── styles/globals.css
│   ├── Dockerfile
│   ├── deploy-s3.sh
│   └── package.json
├── infrastructure/
│   └── cloudformation.yaml            # RDS, SQS, S3, Cognito, CloudWatch
├── docker-compose.yml
└── .env.example
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/signup` | Register new user |
| POST | `/auth/login` | Obtain JWT |
| GET | `/auth/me` | Current user profile |
| GET | `/api/options-chain/{symbol}` | PCR + support/resistance |
| GET | `/api/gamma-walls/{symbol}` | Gamma wall analysis |
| GET | `/api/max-pain/{symbol}` | Max pain per expiry |
| GET | `/api/options-flow/{symbol}` | Smart money flow |
| GET | `/api/positioning-shifts/{symbol}` | Intraday OI shifts |
| GET | `/api/liquidity-traps/{symbol}` | OI concentration traps |
| GET | `/api/alerts/{symbol}` | Alert history |
| GET | `/api/market-summary/{symbol}` | AI plain-language insight |
| GET | `/admin/user-stats` | Admin: user counts |
| GET | `/admin/usage-stats` | Admin: event/snapshot stats |
| GET | `/admin/system-health` | Admin: DB + ingestion health |

All analytics endpoints require `Authorization: Bearer <token>`.

---

## AWS Deployment

### 1 Deploy Infrastructure

```bash
aws cloudformation deploy \
  --stack-name optionthropic-production \
  --template-file infrastructure/cloudformation.yaml \
  --parameter-overrides Env=production DBPassword=<strong-password> \
  --capabilities CAPABILITY_IAM \
  --region ap-south-1
```

### 2 Store secrets in Parameter Store

```bash
aws ssm put-parameter --name /optionthropic/DATABASE_URL  --value "..." --type SecureString
aws ssm put-parameter --name /optionthropic/SECRET_KEY    --value "..." --type SecureString
aws ssm put-parameter --name /optionthropic/OPENAI_API_KEY --value "..." --type SecureString
# … (see apprunner.yaml for full list)
```

### 3 Deploy backend to App Runner

```bash
aws apprunner create-service \
  --service-name optionthropic-backend \
  --source-configuration '{"CodeRepository": {...}}' \
  --region ap-south-1
```

Or push Docker image to ECR and reference it in App Runner console.

### 4 Deploy frontend to S3

```bash
cd frontend
export FRONTEND_BUCKET=<bucket-name-from-cfn-output>
export CLOUDFRONT_DISTRIBUTION_ID=<id-from-cfn-output>
export NEXT_PUBLIC_API_URL=https://<apprunner-url>
bash deploy-s3.sh
```

---

## Data Sources

Set `DATA_SOURCE` in `.env`:

| Value | Description |
|---|---|
| `NSE` | NSE public option chain API (no auth required, rate-limited) |
| `ZERODHA` | Zerodha Kite Connect (requires API key + access token) |
| `ANGEL` | Angel One SmartAPI (requires client credentials + TOTP) |

---

## Authentication

- **Development** (`USE_COGNITO=false`): local bcrypt + JWT (python-jose)
- **Production** (`USE_COGNITO=true`): AWS Cognito user pools — JWKS token verification

---

## Disclaimer

This platform is for **informational and educational purposes only**.
It does not constitute investment advice. Options trading involves substantial risk.
