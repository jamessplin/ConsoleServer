# Manual SONiC ConsoleServer CLI Test Cases

The following cases cannot be fully validated by unattended CLI automation.

| Area | Manual validation required | Reason |
|---|---|---|
| Connect by line | Confirm terminal opens and serial input/output works | Requires attached serial target and interactive terminal |
| Connect by label | Confirm label reaches the expected physical line | Requires known hardware mapping |
| Escape sequence | Confirm interactive session exits cleanly | Requires terminal interaction |
| Shared mode | Open multiple simultaneous clients | Requires multiple terminals or client hosts |
| Maximum clients | Attempt one client beyond the configured limit | Requires concurrent live sessions |
| Exclusive mode | Confirm a second client is rejected | Requires concurrent live sessions |
| Session contents | Verify user, role, IP, client port, and timer values | Requires controlled live clients |
| Idle countdown | Observe time-left decrease and activity reset | Requires time-controlled live session |
| Password authentication | Log in using the created or changed password | Requires authentication workflow and secure secret handling |
| Password prompt | Confirm hidden input and confirmation behavior | Requires interactive TTY |
| Password leakage | Inspect system logs and process visibility during a real change | Requires privileged observation and controlled secret |
| Service restart | Confirm runtime regeneration and reconnect behavior | Interrupts active users and service |
| Save and reboot | Confirm saved configuration returns after cold reboot | Requires reboot coordination |
| Unsaved reboot behavior | Confirm unsaved changes follow normal SONiC behavior | Requires destructive reboot test |
| Physical serial settings | Verify baud, parity, flow control, and stop bits electrically | Requires matching attached serial device |
| Target performance | Measure latency under production load | Depends on target hardware and workload |
