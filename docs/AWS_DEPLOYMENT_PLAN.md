# Optionthropic — AWS Hosting & App Deployment Plan

> **Last updated:** March 2025  
> **Status:** Planning phase — repo on GitHub, ready for AWS deployment

---

## 1. Project Summary

**Optionthropic** is an institutional-grade options analytics SaaS for Indian indices (NIFTY, BANKNIFTY, SENSEX).

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python 3.11), uvicorn |
| Frontend | Next.js 14, React 18, Tailwind, Recharts |
| Database | PostgreSQL 15 (asyncpg) |
| Auth | Development: bcrypt+JWT; Production: AWS Cognito |
| Queue | AWS SQS (alerts) |
| Storage | S3 (frontend), Parameter Store (secrets) |
| Data Sources | NSE (public), Zerodha Kite, Angel One SmartAPI |

### Core Features

- **Analytics:** Gamma walls, Max Pain, Liquidity Traps, Positioning Shifts, Smart Money Flow
- **AI Insights:** GPT-4o / Claude market summaries
- **Alerts:** Rule-based alerts → SQS → RDS persistence
- **Data Ingestion:** 60s polling loop for options + commodity data (runs inside backend)
- **Pro Signals:** Quick signals, swing signals, commodity insights, MCX prices

### Current Architecture (Docker local)

```
[Frontend :3000] → [Backend :8000] → [PostgreSQL :5432]
                          ↓
                   Options Collector (async task)
                   Commodity Collector (async task)
```

---

## 2. AWS Hosting Architecture (Target)

```
                                    ┌─────────────────────────────────────┐
                                    │            CloudFront CDN             │
                                    │  (frontend static / custom domain)   │
                                    └─────────────────┬───────────────────┘
                                                      │
              ┌───────────────────────────────────────┼───────────────────────────────────────┐
              │                                       │                                       │
              ▼                                       ▼                                       │
     ┌────────────────┐                    ┌────────────────┐                               │
     │  S3 Bucket     │                    │  App Runner     │                               │
     │  (static web)  │                    │  (backend API)  │◄──────────────┐               │
     └────────────────┘                    └────────┬────────┘               │               │
                                                    │                        │               │
                                                    │ VPC Connector          │               │
                                                    ▼                        │               │
              ┌──────────────────────────────────────────────────────────────┴───┐           │
              │                         VPC (10.0.0.0/16)                         │           │
              │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │           │
              │  │ Private      │  │ Private      │  │ RDS PostgreSQL          │ │           │
              │  │ Subnet 1     │  │ Subnet 2     │  │ (Multi-AZ in prod)       │ │           │
              │  └──────────────┘  └──────────────┘  └─────────────────────────┘ │           │
              └─────────────────────────────────────────────────────────────────┘           │
                                                                                             │
     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────────────┘
     │ Cognito     │  │ SQS         │  │ Parameter   │  │
     │ User Pool   │  │ Alerts      │  │ Store       │  │
     └─────────────┘  └─────────────┘  └─────────────┘
```

---

## 3. Gaps in Current Setup

| Gap | Detail |
|-----|--------|
| **RDS reachability** | RDS is in private subnets; App Runner default runs in AWS-managed VPC and cannot reach it. Need **App Runner VPC Connector**. |
| **CloudFormation** | No App Runner resource; no VPC Connector; no NAT/IGW if backend needs outbound to NSE/Zerodha. |
| **Frontend deploy** | `next.config.js` uses `output: "standalone"` (Node server). `deploy-s3.sh` expects `next export` (static). Incompatible. |
| **CI/CD** | No GitHub Actions or CodePipeline; deployment is manual. |
| **CloudFront** | Uses deprecated `ForwardedValues`; S3 origin config may need OAI update for best practice. |
| **Secrets** | App Runner expects SSM params; no automated script to sync from `.env.example` template. |

---

## 4. Deployment Phases

### Phase 1: Fix Infrastructure & Deploy Backend (Week 1)

**1.1 Extend CloudFormation**

- [ ] Add **Internet Gateway** + **NAT Gateway** (in public subnet) so App Runner → VPC Connector → RDS path works, and backend can reach NSE/Zerodha APIs.
- [ ] Add **App Runner VPC Connector** (in private subnets) and **Security Group** allowing App Runner → RDS 5432.
- [ ] Add **App Runner Service** (or use ECR-based deployment) with:
  - Source: ECR image from `backend/Dockerfile`
  - Port 8000
  - Env vars from SSM Parameter Store (see `apprunner.yaml`)
  - VPC Connector attached
- [ ] Optional: Add **Route 53** hosted zone + ACM cert for custom domain (`api.optionthropic.io`).

**1.2 SSM Parameters**

Create parameters before first App Runner deploy:

```
/optionthropic/DATABASE_URL      → postgresql+asyncpg://...
/optionthropic/SECRET_KEY        → <random 32+ chars>
/optionthropic/OPENAI_API_KEY    → sk-...
/optionthropic/ANTHROPIC_API_KEY → sk-ant-...
/optionthropic/COGNITO_USER_POOL_ID
/optionthropic/COGNITO_CLIENT_ID
/optionthropic/SQS_QUEUE_URL
```

**1.3 ECR + App Runner**

- [ ] Create ECR repo `optionthropic-backend`.
- [ ] Build and push: `docker build -t optionthropic-backend ./backend && docker push ...`
- [ ] Create App Runner service (via CloudFormation or console) pointing to ECR image.
- [ ] Verify `/health` and `/api/last-refresh` work.

---

### Phase 2: Deploy Frontend (Week 1–2)

**2.1 Choose Strategy**

| Option | Pros | Cons |
|--------|------|------|
| **A: Static S3 + CloudFront** | Cheap, fast, simple | Need `output: 'export'`; no SSR |
| **B: App Runner / ECS for frontend** | Full Next.js SSR | Higher cost, two services |

**Recommendation:** Option A for MVP (most of your pages are client-rendered).

**2.2 Changes for Static Export**

- [ ] In `frontend/next.config.js`: set `output: "export"` when building for S3.
- [ ] Update `deploy-s3.sh` to use `next build` (which produces `out/` with `output: "export"`).
- [ ] Set `NEXT_PUBLIC_API_URL=https://<app-runner-url>` at build time.
- [ ] Set `NEXT_PUBLIC_USE_COGNITO=true` and Cognito IDs for production.

**2.3 Deploy**

- [ ] Run `deploy-s3.sh` with:
  - `FRONTEND_BUCKET` = CloudFormation output
  - `CLOUDFRONT_DISTRIBUTION_ID` = CloudFormation output
  - `NEXT_PUBLIC_API_URL` = App Runner URL
- [ ] Add CORS origin for CloudFront URL in backend if not already covered by `optionthropic.io`.

---

### Phase 3: CI/CD from GitHub (Week 2)

**3.1 GitHub Actions Workflow**

- [ ] `.github/workflows/deploy.yml`:
  - Trigger: push to `main` (or `production` branch)
  - Jobs:
    1. **Backend:** Build Docker image → Push to ECR → Update App Runner service
    2. **Frontend:** Build → Deploy to S3 → CloudFront invalidation
  - Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `OPENAI_API_KEY`, etc. (or use OIDC with GitHub–AWS)

**3.2 Optional: AWS CodePipeline**

- [ ] Connect GitHub repo to CodePipeline.
- [ ] Build stage: CodeBuild for Docker + Next.js.
- [ ] Deploy stage: ECR + App Runner + S3 sync.

---

### Phase 4: Custom Domain & HTTPS (Week 2–3)

- [ ] Route 53 hosted zone for `optionthropic.io`.
- [ ] ACM certificate (us-east-1 for CloudFront).
- [ ] CloudFront alternate domain: `www.optionthropic.io`, `optionthropic.io`.
- [ ] App Runner custom domain: `api.optionthropic.io` (or subdomain of choice).
- [ ] Update CORS in backend for production origins.

---

### Phase 5: Mobile App (Future)

If “create an app” means a **native/mobile app**:

| Approach | Effort | Best For |
|----------|--------|----------|
| **React Native / Expo** | Medium | Reuse logic, single codebase iOS + Android |
| **Flutter** | Medium | Polished UI, good performance |
| **PWA** | Low | Add `manifest.json` + service worker; “Add to Home Screen” |
| **Capacitor** | Low | Wrap existing Next.js/React in native shell |

**Recommendation:** Start with **PWA** (manifest + service worker) for quick “app-like” experience; then evaluate React Native if you need app store presence.

---

## 5. Checklist Summary

### Pre-deployment

- [ ] AWS account with billing enabled
- [ ] Domain (e.g. `optionthropic.io`) if using custom domain
- [ ] API keys: OpenAI, Anthropic (or Bedrock for AWS-native AI)
- [ ] Data source credentials (NSE no auth; Zerodha/Angel if used)

### Infrastructure

- [ ] CloudFormation stack deployed with VPC, RDS, SQS, S3, CloudFront, Cognito
- [ ] App Runner VPC Connector + App Runner service
- [ ] SSM parameters populated
- [ ] ECR repo created

### Backend

- [ ] Docker image builds successfully
- [ ] App Runner service healthy
- [ ] `/health`, `/api/last-refresh` respond
- [ ] Options collector running (check DB for `chain_snapshots`)
- [ ] Cognito login/signup working

### Frontend

- [ ] Static export builds
- [ ] S3 sync + CloudFront invalidation work
- [ ] App loads and calls API
- [ ] Auth flow works with Cognito

### CI/CD

- [ ] GitHub Actions or CodePipeline configured
- [ ] Push to main triggers deploy
- [ ] Rollback strategy documented

---

## 6. Cost Estimate (Monthly, ap-south-1)

| Service | Estimate |
|---------|----------|
| RDS db.t4g.small | ~$15–25 |
| App Runner (min) | ~$25–50 |
| S3 + CloudFront | ~$5–15 |
| Cognito | Free tier (50k MAU) |
| SQS | Negligible |
| **Total** | **~$50–100/month** (MVP) |

---

## 7. Next Steps

1. **Immediate:** Extend `infrastructure/cloudformation.yaml` with VPC Connector, NAT/IGW, and App Runner service.
2. **Immediate:** Add `output: "export"` path for frontend S3 deployment.
3. **Week 1:** Deploy backend to App Runner, verify DB connectivity.
4. **Week 1:** Deploy frontend to S3/CloudFront, test end-to-end.
5. **Week 2:** Add GitHub Actions workflow.
6. **Later:** Custom domain, PWA/mobile app if desired.

---

## 8. Files to Create/Modify

| File | Action |
|------|--------|
| `infrastructure/cloudformation.yaml` | Add VPC Connector, NAT, IGW, App Runner service |
| `infrastructure/README.md` | Document params, outputs, deploy order |
| `frontend/next.config.js` | Support `output: "export"` for S3 builds |
| `frontend/deploy-s3.sh` | Align with `output: export` |
| `.github/workflows/deploy.yml` | New: CI/CD pipeline |
| `scripts/setup-ssm.sh` | New: Bootstrap SSM from env template |
| `docs/AWS_DEPLOYMENT_PLAN.md` | This file |

---

*For questions or updates, refer to the main [README](../README.md).*
