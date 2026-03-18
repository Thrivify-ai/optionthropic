#!/usr/bin/env bash
# Optionthropic frontend — build and deploy to S3 + CloudFront
set -euo pipefail

BUCKET="${FRONTEND_BUCKET:-}"
CLOUDFRONT_ID="${CLOUDFRONT_DISTRIBUTION_ID:-}"
REGION="${AWS_REGION:-ap-south-1}"
API_URL="${NEXT_PUBLIC_API_URL:-}"

if [[ -z "$BUCKET" ]]; then
  echo "ERROR: FRONTEND_BUCKET env var is required" >&2
  exit 1
fi

echo "▶ Installing dependencies…"
npm ci

echo "▶ Building Next.js (static export)…"
NEXT_PUBLIC_API_URL="$API_URL" npm run build

echo "▶ Exporting static files…"
# For static S3 hosting, next.config.js must use output: 'export'
# If using App Runner / server-side rendering, skip this step
npx next export -o out 2>/dev/null || true

if [[ ! -d "out" ]]; then
  echo "WARN: 'out' directory not found — copying .next/static instead"
  mkdir -p out
  cp -r .next/static out/_next
fi

echo "▶ Syncing to s3://${BUCKET}…"
aws s3 sync out/ "s3://${BUCKET}/" \
  --region "$REGION" \
  --delete \
  --cache-control "public,max-age=86400" \
  --exclude "*.html"

# HTML files: no cache for SPA routing
aws s3 sync out/ "s3://${BUCKET}/" \
  --region "$REGION" \
  --exclude "*" \
  --include "*.html" \
  --cache-control "no-cache,no-store,must-revalidate"

if [[ -n "$CLOUDFRONT_ID" ]]; then
  echo "▶ Invalidating CloudFront distribution ${CLOUDFRONT_ID}…"
  aws cloudfront create-invalidation \
    --distribution-id "$CLOUDFRONT_ID" \
    --paths "/*"
fi

echo "✓ Deployment complete."
