# SONiC Console Server Startup Snapshot

## Ownership

The independent console-server application remains SONiC-agnostic:

```text
Standalone Linux:
    seriald.service
        -> server.py --config /etc/seriald/config.json
```

SONiC uses a separate service:

```text
ConfigDB
    -> console-server-config-generate
    -> /run/seriald/config.json
    -> console-server.service
    -> server.py
```

`/etc/seriald/config.json` is read as a bootstrap/template because it contains
application and platform fields that are not modeled in ConfigDB. SONiC never
writes this file. ConfigDB overwrites every field that SONiC owns.

## Startup policy

| Object | Startup behavior |
|---|---|
| Ports | Include every ConfigDB row and override SONiC-owned fields in the matching bootstrap line |
| Groups | Replace bootstrap groups with exactly the ConfigDB groups |
| User metadata | Include ConfigDB role/group metadata only for existing Linux/NSS accounts; Linux/NSS is validation-only |
| Extra bootstrap users | Preserve and log them as unmanaged; remove memberships to undefined groups |
| Passwords | Never read from ConfigDB, emit, log, generate, or modify |
| Product info | Validate and map limits into the application's existing `info` object |

The generator atomically writes `/run/seriald/config.json` with mode `0600`.
If validation fails, the output is not replaced and `console-server.service`
does not start.

## Services

In a SONiC image:

```text
seriald.service:        disabled
console-server.service: enabled
```

The two services conflict because they cannot own the same serial ports and TCP
listeners simultaneously.
