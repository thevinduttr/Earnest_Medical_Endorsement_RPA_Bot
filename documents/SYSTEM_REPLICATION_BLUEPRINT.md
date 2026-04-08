# System Replication Blueprint (Based on CRM_SYSTEM)

## 1. Purpose

This document explains the completed CRM_SYSTEM architecture and Software Engineering (SE) patterns, and provides a full blueprint to build another system with the same structure and quality standards.

Use this as a master reference when creating a new automation platform (same engineering model, different business domain).

## 2. What This Existing System Implements

The current project is a production-style, database-driven automation worker that:

- Polls pending work items from SQL Server.
- Atomically reserves one request per bot to avoid duplicate processing.
- Runs Playwright browser workflows (login, client, lead, prospect flows).
- Downloads and manages attachments from Azure Blob storage.
- Applies validation, mapping, and formatting before execution.
- Updates database lifecycle statuses (PENDING/INPROGRESS/COMPLETED/FAILED).
- Produces rich observability artifacts (logs, screenshots, traces).
- Sends error/success notifications with relevant attachments.
- Supports concurrent multi-bot processing safely.

## 3. Core Architecture (Layered + Modular)

### 3.1 Layers

1. Entry/Orchestration Layer
- main.py: continuous worker loop, lifecycle orchestration, exception boundaries.
- run_multibot.py: multi-instance launcher.

2. Process Layer
- src/process/: business flows broken into feature modules.
- Examples: login, client_process, lead_process, prospect_process.

3. Service Layer
- src/services/db_service/: database connection and request lifecycle operations.
- src/services/blob_service/: document retrieval from cloud storage.

4. Utility/Foundation Layer
- src/utils/: config loading, logging, emailing, validation, mapping, formatting, tracing.

5. Configuration and Locator Layer
- config/: environment-independent settings.
- locators/: UI selectors externalized in YAML.

6. Data/Artifact Layer
- data/: logs, downloaded attachments, outputs, trace artifacts.

### 3.2 Architectural Characteristics

- Strong separation of concerns.
- Config-driven behavior (minimal hardcoding).
- Worker-safe concurrency using DB locking semantics.
- Fault isolation and controlled retries.
- Full traceability per request run.

## 4. SE Patterns Followed

### 4.1 Worker Pattern (Queue Consumer)
- Continuous polling loop consumes pending work items.
- Each loop handles one request lifecycle end-to-end.

### 4.2 Atomic Reservation Pattern
- Request selected and status-updated atomically.
- Prevents race conditions in multi-bot deployments.

### 4.3 Layered Architecture
- Clear boundaries among orchestration, process logic, services, utilities.

### 4.4 Strategy-Like Config Pattern
- Different behavior via YAML config and locator files instead of code branching.

### 4.5 Fail-Fast Validation Pattern
- Validate config/data early.
- Stop run on validation failures and mark FAILED explicitly.

### 4.6 Resilience Pattern
- Retry transient DB errors with backoff.
- Reset stuck INPROGRESS requests.
- Release failed requests for retry when applicable.

### 4.7 Observability Pattern
- Correlated logs per run and bot.
- Screenshots and Playwright traces for root-cause analysis.

## 5. Recommended Folder Structure for New System

Create the new project with the same logical contract:

```text
NEW_AUTOMATION_SYSTEM/
  main.py
  run_multibot.py
  requirements.txt
  SETUP.md
  SECURITY.md
  TRACING.md
  config/
    base.yml
    email.yml
    env/
      db.env
      blob.env
      mail.env
      README.md
  documents/
    ARCHITECTURE.md
    OPERATIONS_RUNBOOK.md
    CHANGE_REQUESTS/
  locators/
    main/
      login_page.yml
      dashboard_page.yml
    module_a/
      create_module_a.yml
      search_module_a.yml
    module_b/
      create_module_b.yml
      search_module_b.yml
  src/
    process/
      login.py
      dashboard.py
      module_a_process/
        module_a_process_main.py
        create_module_a.py
        search_module_a.py
      module_b_process/
        module_b_process_main.py
        create_module_b.py
        search_module_b.py
    services/
      db_service/
        data_service.py
        azure_db_connection.py
        constants.py
        db_utils.py
      blob_service/
        blob_download_service.py
    utils/
      load_data.py
      logger.py
      error_handler.py
      attachment_manager.py
      send_email.py
      mailer.py
      data_mapper.py
      validate_data.py
      metrics.py
      playwright_tracer.py
      support_functions.py
  data/
    attachments/
    logs/
    outputs/
  tests/
    test_setup.py
    test_db_connection.py
    test_attachment_download.py
    test_process_flows.py
```

## 6. Execution Lifecycle You Should Reuse

1. Load global config and bot metadata.
2. Reset stale/stuck requests (crash recovery).
3. Atomically reserve next PENDING request.
4. Build run_id and initialize run-scoped loggers.
5. Clear local temp/attachment workspace.
6. Load credentials + request payload from DB.
7. Apply data mappings and format normalization.
8. Download request documents from blob storage.
9. Start browser context and tracing.
10. Execute login and business process flow.
11. On success, update CRMStatus to SUCCESS/COMPLETED as per your domain contract.
12. On validation error, update status to FAILED and do not release to PENDING.
13. On transient/process error, release request for retry (policy-based).
14. Send notifications with evidence (screenshots, logs, documents).
15. Close browser/resources and continue next loop.

## 7. Database Contract for Multi-Bot Safety

### 7.1 Minimum Required Columns

- RequestId
- CRMStatus (or DomainStatus)
- Priority
- ProcessingStartedAt
- ProcessedByBotId
- LastError

### 7.2 State Machine

- PENDING -> INPROGRESS -> COMPLETED
- PENDING -> INPROGRESS -> FAILED
- INPROGRESS -> PENDING (only for retriable technical failures)

Rule:
- Validation/business-rule failures should end at FAILED.
- Technical transient failures may return to PENDING for retry.

## 8. Configuration Model to Keep

### 8.1 base.yml
- bot_details: id/name/version
- paths: portal URLs
- browser: headless, viewport
- tracing: enabled/screenshots/snapshots/sources

### 8.2 email.yml
- recipients, subjects, SMTP behavior

### 8.3 env/*.env
- DB credentials
- Blob credentials
- Mail credentials

Principles:
- No secrets hardcoded in source.
- Environment-specific values outside code.

## 9. Quality and Reliability Requirements

### 9.1 Logging and Traceability
- Correlate every log with bot_id and request_id.
- Keep run-level artifact folders.
- Capture screenshots at key checkpoints and all failures.
- Persist Playwright trace zip for deep debugging.

### 9.2 Validation Gates
- Validate config keys at startup.
- Validate required DB columns/values before flow steps.
- Throw explicit ValidationError for deterministic stop.

### 9.3 Error Handling Standards
- Centralize domain exceptions.
- Different handling for:
  - validation errors
  - transient network/DB errors
  - unknown fatal errors

### 9.4 Testing Strategy
- Setup and environment validation tests.
- DB connection and retry tests.
- Attachment download tests.
- End-to-end process flow tests.
- Notification content/attachment tests.

## 10. Development Plan for Another System

### Phase 1: Foundation
- Create repository using the folder structure template.
- Implement config loader, logger, and error-handler modules.
- Set up DB and blob service skeletons.

### Phase 2: Request Lifecycle Engine
- Implement atomic reservation + status updates.
- Add stuck-request reset and failure release logic.
- Build run_id and log folder conventions.

### Phase 3: Automation Flows
- Implement login and one business module end-to-end.
- Externalize selectors and flow settings to YAML.

### Phase 4: Reliability and Observability
- Add tracing, screenshots, structured notifications.
- Add attachment pipeline and evidence-based error emails.

### Phase 5: Scale and Hardening
- Add multi-bot launcher and concurrency tests.
- Add integration tests and production runbook.
- Tune retry thresholds, timeout values, and cleanup policies.

## 11. Engineering Checklist (Definition of Done)

- Atomic DB reservation confirmed with concurrent bots.
- No duplicate processing under load.
- Validation errors end in FAILED (no auto-release).
- Transient technical failures are retriable.
- All secrets loaded from env/config only.
- Every run has complete logs + screenshots + optional trace.
- Error notifications include actionable evidence.
- Test suite covers setup, service, flow, and notification paths.
- Operational documents are available for support team handover.

## 12. Notes for Your Next Project

To build another system like this, keep the architecture and lifecycle contract unchanged, and replace only:

- domain-specific process modules,
- data mappings and validation rules,
- locator YAMLs and UI actions,
- database table names/fields,
- notification recipients and templates.

This approach gives you faster delivery, lower defect risk, and easier support at scale.
