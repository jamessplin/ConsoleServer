# 24-Port Data Center Console Server
## Software Specification (Updated Draft)

---

## 1. Scope & Objectives

### 1.1 Scope
This document defines the **software architecture, functional requirements, and non-functional requirements** for a **24-port data center–grade console server**, providing secure, scalable, and reliable out-of-band serial access to network, server, and legacy devices.

### 1.2 Objectives
- Support **24 serial console ports** concurrently
- Provide **network-based, multi-user console access**
- Meet **data center operational requirements** (Netwrok Operation Center, Remote Colocation, Automation)
- Be deployable on **Linux / SONiC–based platforms**
- Serve as the foundation for **commercial-grade console server products**

---

## 2. High-Level Architecture

### 2.1 Logical Architecture
```
+----------------------------+
|        Management Plane    |
|  - User / Auth             |
|  - Configuration           |
|  - Monitoring / Logging    |
+-------------+--------------+
              |
+-------------v--------------+
|        Console Backend     |
|  - Serial ↔ Network bridge |
|  - Multi-user access       |
|  - Port isolation          |
+-------------+--------------+
              |
+-------------v--------------+
|        Serial Devices      |
|  /dev/ttyCOM1 ~ ttyCOM24   |
+----------------------------+
```

---

## 3. Access & Connectivity Model

### 3.1 Supported Access Methods
| Method | Requirement |
|------|-------------|
| SSH (CLI) | **Mandatory** |


### 3.2 Direct Port Access
Each serial port shall be accessible via:
  1. Direct access
    - ssh -p 20001 userName@consoleServerIp
    - ssh userName:com1@consoleServerIp (TODO 1)
    - ssh userName:label@consoleServerIp (TODO 2)
    - ssh username@portIp (TODO 3)
  2. Access via console server CLI

---

## 4. Serial Port & Hardware Abstraction

### 4.1 Programmable Port Pins(TODO 4)
- The system **shall support programmable serial port pins**
  - Support for both major RJ-45 console pinout standards:
    - **Cisco/Yost standard** (used by Cisco, Juniper, etc.)
    - **Arista standard** (used by Arista and some other vendors)
  - Per-port pinout configuration to ensure compatibility with diverse device requirements

### 4.2 Serial Device Mapping
- Serial devices **must be persistently mapped** using udev rules
- Mapping based on **ID_PATH or PCI topology**
- Naming convention:
```
/dev/ttyCOM1 … /dev/ttyCOM24
```

### 4.3 Serial Configuration Parameters
Each port shall support:
- Custom Port Label: Users shall be able to assign meaningful, human-readable names to each console port for easier identification and management.
- Baud rate
- Data bits / parity / stop bits
- Flow control
- Runtime reconfiguration without reboot

---

## 5. Multi-User & Session Management

### 5.1 Multi-Session Access
- The system **must support multiple concurrent user sessions**
- Multiple users may be logged into the console server simultaneously
- Each user may access different serial ports concurrently
- System shall handle ≥48 concurrent sessions (per requirements in Section 11)
- Sessions shall be isolated and independent

### 5.2 Port Access Modes
- **Single-User Mode**
  - Only one user may access a given console port at a time; subsequent login attempts are rejected until the port is released.
- **Shared Mode**
  - Multiple users may access the same console port concurrently, supporting collaborative troubleshooting and monitoring.

### 5.3 Break-Safe Operation
- The system **must prevent accidental BREAK signal transmission**
- BREAK signals shall be:
  - Disabled by default
  - Explicitly authorized per user or role

---

## 6. User Management & Authorization

### 6.1 Authentication
Supported authentication mechanisms:
- Linux PAM (local users)
- SSH public key authentication
- Optional LDAP / RADIUS (TODO 5)

### 6.2 Terminal Login (Per-Port Authentication)
- The system **shall enforce per-port authentication**
- Users may only access ports explicitly authorized to them

### 6.3 Role-Based User Menus
- The system shall provide **role-based user menus**, offering:

- **Operator Role**
  - Simplified navigation for operators
    - View real-time console status
    - Connect to accessible serial ports

- **Console User Role**
  - Restricted access for console users
    - Execute all operator-level commands
    - Configure COM port parameters (e.g., baud rate, data bits, stop bits, etc.)

- **Admin Role**
  - Execute all console user-level commands
  - User management and system configuration
    - Create, modify, and delete user accounts
    - Assign roles (operator, console user, admin)
    - Manage authentication and access policies
    - Audit user activity and generate reports


### 6.4 Group Management
- The system shall support the creation of **Port Groups** to streamline access control and role assignment.

  - **Port Assignment:** Administrators shall define groups by adding specific COM ports to a group profile.
  - **Role Mapping:** Each Group shall be assigned a specific access level (e.g., Operator or Console User) based on the **Role-Based User Menu** configuration.
  - **Group Selection:** Created groups shall serve as the primary unit for user-port authorization.

### 6.5 User Access Assignment
- The system shall provide a centralized user management interface to handle the following:

  - **User Provisioning:** Create, modify, and manage individual user accounts.
  - **Group Association:** Assign users to one or more specific groups to grant corresponding port access and command privileges.
  - **Role Mapping:** Each User can be assigned a specific access level (e.g., Operator or Console User) based on the **Role-Based User Menu** configuration, which will be used by default. If a user's Role Mapping is not set, the access level defined by their assigned group will be used.

---

### Logic Overview (RBAC Mapping)

To ensure clarity for implementation, the relationship between ports, roles, and users is defined as follows:


| Component | Description |
| :--- | :--- |
| **COM Ports** | The physical serial resources (e.g.,  COM1, COM2). |
| **Groups** | A collection of specific Ports assigned a fixed **Role** (Operator/Console). |
| **Users** | Members assigned to Groups to inherit access to the grouped Ports and Role. |

### Example Scenario

| User | Assigned Group | Resulting Access |
| :--- | :--- | :--- |
| **Junior_Tech** | Group_A (Operator) | Can **View/Connect** to Ports 1-4 only. |
| **Senior_Admin** | Group_B (Console) | Can **Configure** parameters for Ports 5-8. |

---

## 7. Automation & Event-Driven Behavior(Phase2)

### 7.1 Automatic Port Connections (TODO 6)
- The system shall support **automatic outbound connections**, including:
  - SSH
  - Telnet
  - TCP
- Triggers may include:
  - Serial data activity
  - Device boot events
  - Predefined schedules

### 7.2 Automation Use Cases(TODO 7)
- Headless device provisioning
- Zero-touch deployment
- Automated log collection

---

## 8. Logging & Storage

### 8.1 Console Logging(TODO 8)
- Per-port persistent console logs
- Configurable:
  - Enable / disable
  - Rotation size
  - Retention policy

---

## 9. Configuration Management(TODO 10)

### 9.1 Configuration Model
- Human-readable configuration format (JSON)
- Per-port configuration blocks
- Runtime reload supported

### 9.2 Configuration Interfaces
| Interface | Requirement |
|---------|-------------|
| CLI (SSH) | Mandatory |
| Role-based menus | Mandatory |
| REST API | Optional (Phase 2) |

---

## 10. Monitoring & Health(TODO 11)

- Backend service health monitoring
- Serial device availability tracking
- Per-port session count visibility
- Syslog integration
- Optional SNMP support

---

## 11. Scalability & Performance

| Item | Requirement |
|----|-------------|
| Serial ports | 24 |
| Concurrent sessions | ≥ 48 |
| CPU usage | <5% typical |
| Memory | <256 MB |

---

## 12. Security Requirements

- No root login required for console access
- Principle of least privilege for backend services
- Protection against:
  - Unauthorized access
  - Session hijacking
  - Accidental device disruption

---

## 13. Out-of-Scope (v1)

- Full-featured Web UI
- Graphical session replay
- Cloud orchestration

---

## 14. Design Principles

- Network-first console access
- Daemon-based backend
- Deterministic serial mapping
- Multi-user safe by design
- Data-center-grade reliability

