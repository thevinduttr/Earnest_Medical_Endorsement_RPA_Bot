# New Project Template With Sample Data and Select Helpers

## 1. Goal

This document shows how to build a new automation project using the same engineering structure as the current CRM system, while adding reusable support functions for:

- selecting menu options
- filling input fields
- choosing dropdown values
- clicking buttons in a declarative flow
- using YAML locator files and sample data files

Use this as the starting point for a new project with the same maintainable structure.

---

## 2. Recommended Project Structure

```text
new_automation_project/
├── main.py
├── run_multibot.py
├── requirements.txt
├── SETUP.md
├── SECURITY.md
├── TRACING.md
├── config/
│   ├── base.yml
│   ├── email.yml
│   └── env/
│       ├── db.env
│       ├── blob.env
│       └── mail.env
├── documents/
│   ├── ARCHITECTURE.md
│   ├── PROCESS_GUIDE.md
│   └── SAMPLE_DATA.md
├── locators/
│   ├── main/
│   │   ├── login_page.yml
│   │   ├── dashboard_page.yml
│   │   └── navigation_menu.yml
│   ├── module_a/
│   │   ├── create_module_a.yml
│   │   └── search_module_a.yml
│   └── module_b/
│       ├── create_module_b.yml
│       └── search_module_b.yml
├── data/
│   ├── input/
│   │   ├── sample_data.json
│   │   └── sample_data.csv
│   ├── attachments/
│   ├── logs/
│   └── outputs/
├── src/
│   ├── process/
│   │   ├── login.py
│   │   ├── dashboard.py
│   │   ├── module_a_process/
│   │   │   ├── module_a_process_main.py
│   │   │   ├── create_module_a.py
│   │   │   └── search_module_a.py
│   │   └── module_b_process/
│   │       ├── module_b_process_main.py
│   │       ├── create_module_b.py
│   │       └── search_module_b.py
│   ├── services/
│   │   ├── db_service/
│   │   │   ├── data_service.py
│   │   │   ├── azure_db_connection.py
│   │   │   ├── constants.py
│   │   │   └── db_utils.py
│   │   └── blob_service/
│   │       └── blob_download_service.py
│   └── utils/
│       ├── load_data.py
│       ├── logger.py
│       ├── error_handler.py
│       ├── support_functions.py
│       ├── attachment_manager.py
│       ├── mailer.py
│       ├── send_email.py
│       ├── data_mapper.py
│       ├── validate_data.py
│       ├── metrics.py
│       └── playwright_tracer.py
└── tests/
    ├── test_setup.py
    ├── test_db_connection.py
    ├── test_navigation.py
    ├── test_field_selection.py
    └── test_process_flow.py
```

---

## 3. Existing Locator Style You Can Reuse

Your current locator pattern is already good for a new project because it keeps UI targets outside Python code.

### Example menu locator file

```yaml
# locators/sukoon/endorsement_menu.yml
menu:
  # Main Policy Servicing menu
  policy_servicing: "//li[@id='menu-policy']"

  # Member submenu
  member_menu: "//a[normalize-space()='Member']"

  # Add/Delete operations
  add_operation: "//a[normalize-space()='Add']"
  delete_operation: "//a[normalize-space()='Delete']"

  # Manual and Batch actions for add
  manual_add: "//a[@href='/PolicyServicing/member/manualaddition']"
  batch_add: "//a[@href='/PolicyServicing/Member/BatchAddition']"

  # Manual and Batch actions for delete
  manual_delete: "//a[@href='/PolicyServicing/Member/ManualDelete']"
  batch_delete: "//a[@href='/PolicyServicing/Member/BatchDeletion']"
```

### Why this structure works

- Each page or menu has its own YAML file.
- XPath/CSS selectors stay in one place.
- Updating the UI does not require rewriting business logic.
- Different modules can share the same helper functions.

---

## 4. Sample Data File

A new project should store test or request data in a structured file, usually JSON, CSV, or database-backed rows.

### Example JSON data

```json
[
  {
    "PolicyNumber": "POL-10001",
    "MemberName": "John Smith",
    "MemberType": "Individual",
    "OperationType": "Add",
    "ActionMode": "Manual",
    "Nationality": "United Arab Emirates",
    "EmiratesID": "784-1987-1234567-1",
    "Mobile": "0501234567",
    "Email": "john.smith@example.com",
    "Plan": "Gold",
    "Gender": "Male"
  },
  {
    "PolicyNumber": "POL-10002",
    "MemberName": "Aisha Khan",
    "MemberType": "Family",
    "OperationType": "Delete",
    "ActionMode": "Batch",
    "Nationality": "Pakistan",
    "EmiratesID": "784-1990-7654321-9",
    "Mobile": "0559876543",
    "Email": "aisha.khan@example.com",
    "Plan": "Silver",
    "Gender": "Female"
  }
]
```

### Example CSV data

```csv
PolicyNumber,MemberName,MemberType,OperationType,ActionMode,Nationality,EmiratesID,Mobile,Email,Plan,Gender
POL-10001,John Smith,Individual,Add,Manual,United Arab Emirates,784-1987-1234567-1,0501234567,john.smith@example.com,Gold,Male
POL-10002,Aisha Khan,Family,Delete,Batch,Pakistan,784-1990-7654321-9,0559876543,aisha.khan@example.com,Silver,Female
```

---

## 5. Support Function Pattern For Select / Fill / Click

The current CRM system already follows a reusable action model in `src/utils/support_functions.py`.

### Core helper responsibilities

- `fill_field()` for text inputs.
- `select_option()` for dropdowns.
- `click_element()` for buttons and menu items.
- `run_actions()` for declarative sequences.
- `wait_for_next_step()` for page transition checks.
- `wait_for_not_visible()` for loaders and overlays.

### Suggested action schema

Use a declarative action list instead of writing one-off Playwright commands everywhere.

```python
actions = [
    {"type": "click", "key": "policy_servicing", "label": "Policy Servicing Menu"},
    {"type": "click", "key": "member_menu", "label": "Member Menu"},
    {"type": "click", "key": "add_operation", "label": "Add Operation"},
    {"type": "click", "key": "manual_add", "label": "Manual Add"},
    {"type": "fill", "key": "member_name", "label": "Member Name", "value_col": "MemberName"},
    {"type": "select", "key": "member_type", "label": "Member Type", "value_col": "MemberType"},
    {"type": "select", "key": "plan", "label": "Plan", "value_col": "Plan"},
    {"type": "click", "key": "save_button", "label": "Save"}
]
```

### Example support function for a select field

If you want a custom helper for select/fill behavior in the new project, use a wrapper like this:

```python
async def fill_or_select(page, action, selectors, df, logger):
    key = action["key"]
    label = action["label"]
    field_type = action.get("type")
    selector = selectors[key]

    if field_type == "fill":
        value = df.iloc[0][action["value_col"]]
        await fill_field(page, selector, value, label, logger)

    elif field_type == "select":
        value = df.iloc[0][action["value_col"]]
        await select_option(page, selector, label, logger, label=str(value))

    elif field_type == "click":
        await click_element(page, selector, label, logger)
```

### Example for menu navigation helper

```python
async def open_endorsement_menu(page, menu_selectors, logger):
    await click_element(page, menu_selectors["policy_servicing"], "Policy Servicing", logger)
    await click_element(page, menu_selectors["member_menu"], "Member Menu", logger)
```

### Example for add operation helper

```python
async def open_add_member(page, menu_selectors, logger):
    await click_element(page, menu_selectors["add_operation"], "Add Operation", logger)
    await click_element(page, menu_selectors["manual_add"], "Manual Add", logger)
```

### Example for delete operation helper

```python
async def open_delete_member(page, menu_selectors, logger):
    await click_element(page, menu_selectors["delete_operation"], "Delete Operation", logger)
    await click_element(page, menu_selectors["manual_delete"], "Manual Delete", logger)
```

---

## 6. Sample YAML For New Project Selectors

### Menu YAML

```yaml
menu:
  policy_servicing: "//li[@id='menu-policy']"
  member_menu: "//a[normalize-space()='Member']"
  add_operation: "//a[normalize-space()='Add']"
  delete_operation: "//a[normalize-space()='Delete']"
  manual_add: "//a[@href='/PolicyServicing/member/manualaddition']"
  batch_add: "//a[@href='/PolicyServicing/Member/BatchAddition']"
  manual_delete: "//a[@href='/PolicyServicing/Member/ManualDelete']"
  batch_delete: "//a[@href='/PolicyServicing/Member/BatchDeletion']"
```

### Form YAML

```yaml
member_form:
  member_name: "//input[@name='MemberName']"
  member_type: "//select[@name='MemberType']"
  nationality: "//select[@name='Nationality']"
  emirates_id: "//input[@name='EmiratesId']"
  mobile: "//input[@name='Mobile']"
  email: "//input[@name='Email']"
  plan: "//select[@name='Plan']"
  save_button: "//button[@type='submit']"
```

---

## 7. Example Process Flow For The New Project

1. Load config and locators.
2. Load sample data from JSON/CSV/DB.
3. Login to the portal.
4. Navigate to the correct menu using support functions.
5. Fill inputs using `fill_field()`.
6. Select dropdown values using `select_option()`.
7. Click submission buttons using `click_element()`.
8. Wait for success marker or validation message.
9. Save logs, screenshots, and trace files.
10. Send success or error notifications.

---

## 8. Example Declarative Flow Using Existing Helper Style

```python
async def member_add_flow(page, df, selectors, logger):
    actions = [
        {"type": "click", "key": "policy_servicing", "label": "Policy Servicing"},
        {"type": "click", "key": "member_menu", "label": "Member Menu"},
        {"type": "click", "key": "add_operation", "label": "Add Operation"},
        {"type": "click", "key": "manual_add", "label": "Manual Add"},
        {"type": "fill", "key": "member_name", "label": "Member Name", "value_col": "MemberName"},
        {"type": "select", "key": "member_type", "label": "Member Type", "value_col": "MemberType"},
        {"type": "select", "key": "plan", "label": "Plan", "value_col": "Plan"},
        {"type": "click", "key": "save_button", "label": "Save", "validation_check": True},
    ]

    await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger)
```

---

## 9. Database Fields You Should Plan For

If the new system will also process queued requests, keep the same lifecycle style.

### Suggested request columns

- RequestId
- Status
- Priority
- ProcessedByBotId
- ProcessingStartedAt
- LastError
- CreatedAt
- UpdatedAt

### Suggested statuses

- PENDING
- INPROGRESS
- COMPLETED
- FAILED

---

## 10. Minimal Support Function Template

If you want a new helper module for the next project, keep the same shape:

```python
# src/utils/support_functions.py

async def fill_field(...):
    pass

async def select_option(...):
    pass

async def click_element(...):
    pass

async def run_actions(...):
    pass

async def wait_for_next_step(...):
    pass
```

Recommended rule:
- keep all browser interactions in one helper layer
- keep business flow code clean and short
- store all selectors in YAML
- store all sample request data outside code

---

## 11. Sample Folder Mapping For Your Endorsement Case

For the endorsement menu you shared, a new project could use this module split:

```text
src/process/endorsement_process/
├── endorsement_process_main.py
├── member_add.py
├── member_delete.py
├── menu_navigation.py
├── batch_add.py
└── batch_delete.py
```

```text
locators/sukoon/
├── endorsement_menu.yml
├── member_add.yml
├── member_delete.yml
└── endorsement_search.yml
```

This gives you one file for navigation and separate files for each form.

---

## 12. Final Recommendation

For the next project, keep the same engineering discipline used here:

- YAML-driven selectors
- reusable Playwright support helpers
- one process module per business flow
- config files for environment details
- structured sample data
- run-level logging and tracing
- clear status lifecycle in the database

That combination is what makes the current codebase maintainable and easy to extend.
