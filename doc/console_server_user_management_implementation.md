# Console Server User Management Implementation Guide

## 1. Purpose

This document defines implementation details for console-server user management across:

- SONiC CLI
- REST operations
- Linux/NSS authentication
- ConfigDB non-secret metadata
- CVL/YANG validation
- transaction and rollback behavior

It complements:

```text
console_server_yang_cvl_design_note.md
```

The design note remains the source of truth for table structure, YANG schema, CLI naming, and ownership boundaries.

---

## 2. Storage Boundary

### 2.1 Stored in ConfigDB

Store only non-secret console-server metadata:

```text
CONSOLE_SERVER_USER
    username
    role

CONSOLE_SERVER_USER_GROUP
    username
    groupname
```

Example:

```json
{
    "CONSOLE_SERVER_USER": {
        "tech1": {
            "role": "operator"
        }
    },
    "CONSOLE_SERVER_USER_GROUP": {
        "tech1|Group_A": {},
        "tech1|Group_B": {}
    }
}
```

### 2.2 Stored in Linux Authentication Backend

Store and manage through the Linux authentication backend:

```text
Linux account identity
password hash
password policy state
account lock/expiry state
```

### 2.3 Never Stored or Returned

The password must never be:

- stored in ConfigDB;
- represented as a normal configuration leaf;
- returned by REST GET;
- printed by `show console-server user`;
- written to logs;
- included in error messages.

Password is accepted only as a transient CLI/REST operation input.

---

## 3. Validation Layers

### 3.1 YANG/CVL Validation

YANG/CVL validates ConfigDB relationships:

```text
CONSOLE_SERVER_USER_GROUP.username
    → references CONSOLE_SERVER_USER.username

CONSOLE_SERVER_USER_GROUP.groupname
    → references CONSOLE_SERVER_GROUP.groupname
```

This validates ConfigDB referential integrity only.

It does not prove that the Linux/NSS account exists.

### 3.2 Linux/NSS Validation

The shared manager must validate the external account separately:

```python
def validate_local_user_exists(username: str) -> None:
    """Raise an error if the configured Linux/NSS backend cannot resolve the user."""
```

The implementation must use the system account-resolution mechanism. Do not read `/etc/passwd` directly.

Preferred lookup order:

1. an NSS-aware Python or system API;
2. `getent passwd <username>` when required by the platform;
3. a backend adapter for LDAP or another configured identity provider.

For a strictly local SONiC deployment, Python's `pwd.getpwnam()` may be used if it correctly follows the platform's NSS configuration.

---

## 4. Shared User-Management API

### 4.1 Lookup and Validation

```python
def local_user_exists(username: str) -> bool:
    """Return whether the configured Linux/NSS backend resolves the user."""
```

```python
def validate_local_user_exists(username: str) -> None:
    """Raise CONSOLE_SERVER_USER_NOT_FOUND when the user does not exist."""
```

```python
def validate_local_user_not_exists(username: str) -> None:
    """Raise CONSOLE_SERVER_USER_ALREADY_EXISTS when the user already exists."""
```

```python
def validate_username(username: str) -> None:
    """Validate length and syntax before invoking the Linux backend."""
```

```python
def validate_group_names(groups: list[str]) -> None:
    """Confirm every referenced console-server group exists."""
```

### 4.2 Linux Account Operations

```python
def create_local_user(username: str, password: str) -> None:
    """Create the Linux account and set its initial password."""
```

```python
def set_local_user_password(username: str, password: str) -> None:
    """Update the Linux password without storing it in ConfigDB."""
```

```python
def delete_local_user(username: str) -> None:
    """Delete the Linux account according to the approved account-removal policy."""
```

### 4.3 ConfigDB Metadata Operations

```python
def set_user_metadata(
    username: str,
    role: str,
    groups: list[str],
) -> None:
    """Transactionally write CONSOLE_SERVER_USER and normalized user-group mappings."""
```

```python
def delete_user_metadata(username: str) -> None:
    """Delete user-group mappings and the user metadata entry."""
```

```python
def get_user_metadata(username: str) -> dict:
    """Return non-secret role and group metadata."""
```

### 4.4 High-Level Operations

```python
def add_user(
    username: str,
    password: str,
    role: str = "none",
    groups: list[str] | None = None,
) -> None:
    """Create a new Linux user and persist non-secret console-server metadata."""
```

```python
def update_user(
    username: str,
    password: str | None = None,
    role: str | None = None,
    groups: list[str] | None = None,
) -> None:
    """Update an existing user's password and/or non-secret metadata."""
```

```python
def remove_user(username: str) -> None:
    """Remove ConfigDB metadata and delete the Linux account."""
```


High-level `add_user` / `update_user` behavior:

```text
Linux user absent + password absent:
    reject with CONSOLE_SERVER_PASSWORD_REQUIRED

Linux user absent + password present:
    create Linux account and ConfigDB metadata

Linux user present + password absent:
    leave password unchanged; update supplied metadata

Linux user present + password present:
    update password and supplied metadata

Linux user present + ConfigDB metadata absent:
    import/create the missing metadata without recreating the Linux account
```

---

## 5. REST/YANG Operation Inputs

Standard YANG does not define a general write-only configuration leaf.

Password should be modeled only as an operation input when the selected SONiC REST framework supports YANG RPC/action operations.

Example:

```yang
rpc console-server-user-add {
    input {
        leaf username {
            type string {
                length "1..32";
                pattern '[A-Za-z_][A-Za-z0-9_-]*';
            }
            mandatory true;
        }

        leaf password {
            type string {
                length "1..128";
            }
            mandatory true;
        }

        leaf role {
            type enumeration {
                enum none;
                enum operator;
                enum console_user;
                enum admin;
            }
            default "none";
        }

        leaf-list groups {
            type leafref {
                path "/cs:sonic-console-server/cs:CONSOLE_SERVER_GROUP/cs:CONSOLE_SERVER_GROUP_LIST/cs:groupname";
            }
        }
    }
}
```

If the selected SONiC REST framework does not support arbitrary YANG RPC/action nodes, define dedicated operation endpoints with the same storage and security rules.

---

## 6. Operation Semantics

### 6.1 Add New User

Required flow:

```text
1. Validate username syntax.
2. Validate every referenced console-server group.
3. Confirm the Linux/NSS user does not already exist.
4. Create the Linux user.
5. Set the initial password.
6. Build CONSOLE_SERVER_USER metadata.
7. Build normalized CONSOLE_SERVER_USER_GROUP mappings.
8. Run CVL/schema validation.
9. Commit ConfigDB metadata.
10. Return success.
```

For a new user, password is required.

### 6.2 Update Existing User

Required flow:

```text
1. Validate username syntax.
2. Confirm the Linux/NSS user exists.
3. Validate groups when supplied.
4. Update password when supplied.
5. Build the complete new metadata state.
6. Run CVL/schema validation.
7. Commit ConfigDB metadata transactionally.
8. Return success.
```

For an existing-user update, password is optional. If omitted, the existing password remains unchanged.


### 6.2.1 Existing Linux User Without ConfigDB Metadata

If the Linux/NSS user already exists but `CONSOLE_SERVER_USER` metadata is missing, treat `user add` as an import/update operation.

Required flow:

```text
1. Validate username syntax.
2. Confirm the Linux/NSS user exists.
3. Do not recreate the Linux account.
4. Validate supplied groups.
5. Update the password only if one is supplied.
6. Create the missing CONSOLE_SERVER_USER metadata.
7. Create normalized CONSOLE_SERVER_USER_GROUP mappings.
8. Run CVL/schema validation.
9. Commit ConfigDB metadata transactionally.
10. Return success.
```

This behavior allows pre-existing SONiC/Linux users to be enrolled in console-server authorization without duplicate account creation.

### 6.3 Delete User

Required flow:

```text
1. Confirm the Linux/NSS user exists.
2. Confirm the user is eligible for deletion.
3. Remove CONSOLE_SERVER_USER_GROUP mappings.
4. Remove CONSOLE_SERVER_USER metadata.
5. Delete the Linux account.
6. Return success.
```

System accounts and protected built-in users must not be deletable.

---

## 7. Transaction and Rollback Policy

Linux account operations and ConfigDB updates are not one native transaction.

The implementation must define compensating rollback.

### 7.1 Add-User Rollback

If Linux account creation succeeds but ConfigDB validation or commit fails:

```text
1. Remove any partially written ConfigDB entries.
2. Delete the newly created Linux account.
3. Return the original ConfigDB/CVL error.
4. Log the rollback result without sensitive data.
```

### 7.2 Update-User Rollback

Prefer validating all ConfigDB changes before changing the password.

If metadata update fails after a password change:

- ConfigDB must remain unchanged.
- The password change may not be automatically reversible.
- The API must clearly report partial failure.

### 7.3 Delete-User Rollback

Preferred order:

```text
1. Validate the complete delete request.
2. Snapshot current non-secret ConfigDB metadata.
3. Remove ConfigDB metadata.
4. Delete Linux account.
```

If Linux account deletion fails, restore the saved ConfigDB metadata.

---

## 8. Error Contract

| Condition | Error code | CLI exit | REST status |
|---|---|---:|---:|
| User not found | `CONSOLE_SERVER_USER_NOT_FOUND` | 1 | 404 |
| User already exists | `CONSOLE_SERVER_USER_ALREADY_EXISTS` | 1 | 409 |
| Group not found | `CONSOLE_SERVER_GROUP_NOT_FOUND` | 1 | 404 |
| Invalid username | `CONSOLE_SERVER_USERNAME_INVALID` | 1 | 400 |
| Password required | `CONSOLE_SERVER_PASSWORD_REQUIRED` | 1 | 400 |
| Password rejected by policy | `CONSOLE_SERVER_PASSWORD_POLICY_FAILED` | 1 | 400 |
| Authentication backend failure | `CONSOLE_SERVER_USER_BACKEND_ERROR` | 1 | 500 |
| ConfigDB/CVL validation failure | `CONSOLE_SERVER_CONFIG_VALIDATION_FAILED` | 1 | 400 |
| Rollback failure | `CONSOLE_SERVER_USER_ROLLBACK_FAILED` | 1 | 500 |
| Protected user | `CONSOLE_SERVER_USER_PROTECTED` | 1 | 403 |

Never include password content in an error response.

---

## 9. Security Requirements

- Require administrator privilege for user add, update, delete, and password operations.
- Never log passwords.
- Never return passwords.
- Never store passwords in ConfigDB.
- Never include passwords in diagnostic dumps.
- Prefer protected REST request bodies over URL/query parameters.
- Avoid exposing passwords in process arguments or shell history where practical.
- Prefer an interactive prompt, standard input, or secure secret input mechanism for local CLI use.
- Apply the platform password policy through the Linux authentication backend.
- Reject attempts to delete or modify protected built-in users according to policy.
- Ensure temporary files are not used for plaintext passwords.
- Redact sensitive input from audit logs.

---

## 10. Show Behavior

`show console-server user` may display:

```text
username
console-server role
console-server group membership
```

It must not display:

```text
password
password hash
authentication tokens
```

---

## 11. Test Plan

### 11.1 Unit Tests

- valid and invalid username syntax;
- local user exists / does not exist;
- referenced group exists / does not exist;
- normalized user-group mapping generation;
- password omitted for new user;
- password optional for existing-user update;
- protected-user rejection;
- backend exception mapping;
- rollback paths.

### 11.2 Integration Tests

- create Linux user and ConfigDB metadata;
- update role only;
- update groups only;
- update password only;
- update password and metadata together;
- delete user and mappings;
- CVL rejects missing user metadata reference;
- CVL rejects missing group reference;
- Linux backend failure leaves ConfigDB unchanged;
- ConfigDB failure rolls back newly created Linux user;
- show output never reveals password.

### 11.3 REST Tests

- password accepted only in operation input;
- password absent from GET responses;
- password absent from logs;
- correct HTTP status and error code;
- authorization enforced;
- malformed payload rejected.

---

## 12. Implementation Checklist

- [ ] Define the Linux/NSS backend adapter.
- [ ] Implement `local_user_exists`.
- [ ] Implement `validate_local_user_exists`.
- [ ] Implement `validate_local_user_not_exists`.
- [ ] Implement username and group validation.
- [ ] Implement Linux account creation.
- [ ] Implement password set/update.
- [ ] Implement protected-user policy.
- [ ] Implement ConfigDB user metadata transaction.
- [ ] Implement normalized user-group mappings.
- [ ] Implement compensating rollback.
- [ ] Implement fixed CLI/REST error mapping.
- [ ] Add password redaction tests.
- [ ] Add end-to-end create/update/delete tests.
