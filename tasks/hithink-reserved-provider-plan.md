# Implementation Plan: HiThink reserved provider

## Overview

Register HiThink as a disabled-by-default, catalog-only provider and put its API key under the centralized credential store. This slice must not change the active Tushare route or issue network requests.

## Architecture decisions

- Provider key: `hithink`.
- Credential file: centralized secrets directory, never repository-local.
- Runtime factory: intentionally not added in this slice; the provider remains reserved until its first dataset contract is approved.
- Catalog capabilities: research, market snapshot, stock daily bars, stock master data, financials, and valuations as advertised upstream surfaces; no ETF production capability is claimed.

## Acceptance criteria

- [ ] `CredentialStore` resolves the HiThink credential through the centralized file.
- [ ] HiThink is visible in the provider catalog but is disabled and not runtime-selectable.
- [ ] Existing provider and architecture tests remain green.
- [ ] No test or log contains the real credential and no network call is made.
