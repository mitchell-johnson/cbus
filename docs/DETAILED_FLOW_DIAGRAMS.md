# C-Bus Library - Detailed Flow Diagrams

## Table of Contents
1. [System Initialization Flow](#system-initialization-flow)
2. [Packet Processing Flows](#packet-processing-flows)
3. [Command Execution Flows](#command-execution-flows)
4. [Event Handling Flows](#event-handling-flows)
5. [Error Handling and Recovery](#error-handling-and-recovery)
6. [Integration Flows](#integration-flows)

## System Initialization Flow

### Application Startup Sequence

```mermaid
sequenceDiagram
    participant Main
    participant cmqttd
    participant MqttClient
    participant CBusHandler
    participant PCIProtocol
    participant PCI
    
    Main->>cmqttd: Start Application
    cmqttd->>cmqttd: Parse Arguments
    cmqttd->>cmqttd: Load CBZ Labels
    
    alt Serial Connection
        cmqttd->>PCIProtocol: Create Serial Connection
    else TCP Connection
        cmqttd->>PCIProtocol: Create TCP Connection
    end
    
    PCIProtocol->>PCI: Establish Connection
    PCI-->>PCIProtocol: Connection ACK
    
    PCIProtocol->>PCIProtocol: connection_made()
    PCIProtocol->>PCI: Send Reset Command
    PCI-->>PCIProtocol: Reset Confirmation
    
    PCIProtocol->>PCIProtocol: Start Timesync Task
    PCIProtocol->>PCIProtocol: Start Retry Task
    
    cmqttd->>MqttClient: Connect to Broker
    MqttClient->>MqttClient: on_connect()
    MqttClient->>MqttClient: Publish All Lights Config
    MqttClient->>CBusHandler: Request Initial Status
    
    loop For each Application
        CBusHandler->>PCIProtocol: Request Status Block
        PCIProtocol->>PCI: Status Request
        PCI-->>PCIProtocol: Level Reports
        PCIProtocol->>CBusHandler: Process Reports
        CBusHandler->>MqttClient: Update States
    end
```

### Connection Recovery Flow

```mermaid
flowchart TD
    A[Connection Lost] --> B[connection_lost() Called]
    B --> C[Clean Up Resources]
    C --> D[Clear Confirmation Codes]
    C --> E[Clear Pending Packets]
    C --> F[Clear Group Database]
    
    D --> G[Set Reconnect Flag]
    E --> G
    F --> G
    
    G --> H{Auto Reconnect?}
    H -->|Yes| I[Wait Backoff Period]
    H -->|No| J[Exit]
    
    I --> K[Attempt Reconnection]
    K --> L{Success?}
    L -->|Yes| M[connection_made()]
    L -->|No| N[Increase Backoff]
    
    M --> O[Reset PCI]
    O --> P[Restore Subscriptions]
    P --> Q[Request Full Status]
    Q --> R[Resume Normal Operation]
    
    N --> S{Max Retries?}
    S -->|No| I
    S -->|Yes| J
```

## Packet Processing Flows

### Incoming Packet Processing

```mermaid
flowchart TD
    A[Raw Bytes Received] --> B[Append to Buffer]
    B --> C{Buffer Has Data?}
    C -->|No| Z[Wait for More Data]
    C -->|Yes| D[Look for Packet Start]
    
    D --> E{Valid Start?}
    E -->|No| F[Discard Invalid Bytes]
    E -->|Yes| G[Identify Packet Type]
    
    F --> C
    
    G --> H{Complete Packet?}
    H -->|No| Z
    H -->|Yes| I[Validate Checksum]
    
    I --> J{Checksum OK?}
    J -->|No| K[Log Error]
    J -->|Yes| L[Extract Packet]
    
    K --> F
    
    L --> M{Packet Type?}
    M -->|Reset| N[Handle Reset]
    M -->|Confirmation| O[Handle Confirmation]
    M -->|PM| P[Handle Point-to-Multipoint]
    M -->|PP| Q[Handle Point-to-Point]
    M -->|Error| R[Handle Error]
    M -->|Other| S[Log Unknown]
    
    N --> T[Process & Remove from Buffer]
    O --> T
    P --> T
    Q --> T
    R --> T
    S --> T
    
    T --> C
```

### SAL/CAL Packet Decoding

```mermaid
flowchart LR
    subgraph "PM Packet Processing"
        PM1[PM Packet] --> PM2[Extract Header]
        PM2 --> PM3[Get Application]
        PM3 --> PM4{Application Type?}
        PM4 -->|Lighting| PM5[Parse LightingSAL]
        PM4 -->|Clock| PM6[Parse ClockSAL]
        PM4 -->|Temperature| PM7[Parse TempSAL]
        PM5 --> PM8[Emit Event]
        PM6 --> PM8
        PM7 --> PM8
    end
    
    subgraph "PP Packet Processing"
        PP1[PP Packet] --> PP2[Extract Header]
        PP2 --> PP3[Get CAL Type]
        PP3 --> PP4{CAL Type?}
        PP4 -->|Extended| PP5[Parse ExtendedCAL]
        PP4 -->|Standard| PP6[Parse StandardCAL]
        PP4 -->|Reply| PP7[Parse ReplyCAL]
        PP5 --> PP8[Process Report]
        PP6 --> PP8
        PP7 --> PP8
    end
```

## Command Execution Flows

### Lighting Command Flow

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant MQTT as MQTT Broker
    participant MC as MqttClient
    participant CBH as CBusHandler
    participant PCI as PCIProtocol
    participant HW as PCI Hardware
    
    HA->>MQTT: Publish Command
    Note right of HA: Topic: cbus_001/set<br/>Payload: {"state":"ON",<br/>"brightness":128,<br/>"transition":5}
    
    MQTT->>MC: on_message()
    MC->>MC: Parse JSON Payload
    MC->>MC: Validate Parameters
    
    alt Instant On (brightness=255, transition=0)
        MC->>CBH: lighting_group_on()
        CBH->>PCI: Send ON Command
    else Instant Off
        MC->>CBH: lighting_group_off()
        CBH->>PCI: Send OFF Command
    else Ramp/Fade
        MC->>MC: Calculate Ramp Rate
        MC->>CBH: lighting_group_ramp()
        CBH->>PCI: Send RAMP Command
    end
    
    PCI->>PCI: Get Confirmation Code
    PCI->>PCI: Build Packet
    PCI->>HW: Send Packet
    
    HW-->>PCI: Confirmation
    PCI->>PCI: Release Code
    PCI->>CBH: Command Confirmed
    CBH->>MC: Update State
    MC->>MQTT: Publish State Update
    MQTT-->>HA: State Changed
```

### Status Request Flow

```mermaid
flowchart TD
    A[Status Request Triggered] --> B{Request Type?}
    
    B -->|Initial Connect| C[Request All Applications]
    B -->|Periodic Sync| D[Request Known Groups]
    B -->|Manual Request| E[Request Specific Group]
    
    C --> F[For Each Application 0x30-0x5F]
    D --> G[For Each Known Application]
    E --> H[Single Application]
    
    F --> I[Create Status Requests]
    G --> I
    H --> I
    
    I --> J[Split into 32-Group Blocks]
    J --> K[Throttle Requests]
    
    K --> L[Send Status Request]
    L --> M[Wait for Response]
    
    M --> N{Response Type?}
    N -->|Level Report| O[Process Levels]
    N -->|Binary Report| P[Process Binary]
    N -->|Timeout| Q[Log Error]
    
    O --> R[Update Group States]
    P --> R
    
    R --> S{More Blocks?}
    S -->|Yes| K
    S -->|No| T[Status Complete]
    
    Q --> S
```

### Confirmation Code Management

```mermaid
stateDiagram-v2
    [*] --> Available: Initialize
    
    Available --> InUse: Acquire Code
    InUse --> Waiting: Packet Sent
    
    Waiting --> Available: Confirmation Received
    Waiting --> Retry: Timeout (< Max Retries)
    Waiting --> Failed: Timeout (Max Retries)
    
    Retry --> Waiting: Resend Packet
    Failed --> Available: Release Code
    
    note right of InUse
        Code is marked with timestamp
        for timeout tracking
    end note
    
    note right of Failed
        Log error and clean up
        resources
    end note
```

## Event Handling Flows

### C-Bus Event to MQTT Flow

```mermaid
flowchart TD
    A[C-Bus Event] --> B[PCI Receives]
    B --> C[PCIProtocol Decodes]
    
    C --> D{Event Type?}
    
    D -->|Light On| E[on_lighting_group_on()]
    D -->|Light Off| F[on_lighting_group_off()]
    D -->|Light Ramp| G[on_lighting_group_ramp()]
    D -->|Clock Update| H[on_clock_update()]
    D -->|Level Report| I[on_level_report()]
    
    E --> J[CBusHandler Process]
    F --> J
    G --> J
    H --> K[Update System Time]
    I --> L[Process Multiple Groups]
    
    J --> M{Group Published?}
    M -->|No| N[Publish Config]
    M -->|Yes| O[Skip Config]
    
    N --> P[Update MQTT State]
    O --> P
    
    L --> Q[For Each Level]
    Q --> M
    
    P --> R[Publish to MQTT]
    R --> S[Update Binary Sensor]
    S --> T[Event Complete]
```

### MQTT Discovery Flow

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant MQTT as MQTT Broker
    participant MC as MqttClient
    participant DB as GroupDB
    
    Note over HA,DB: Initial Connection
    
    MC->>MQTT: Connect
    MQTT-->>MC: Connected
    
    MC->>MC: publish_all_lights()
    
    loop For Each Known Group
        MC->>DB: Get Group Info
        DB-->>MC: Label, Application
        
        MC->>MQTT: Publish Config Topic
        Note right of MC: homeassistant/light/<br/>cbus_XXX/config
        
        MC->>MQTT: Subscribe to Set Topic
        Note right of MC: homeassistant/light/<br/>cbus_XXX/set
        
        MC->>DB: Mark as Published
    end
    
    MC->>MQTT: Publish Meta Device
    Note right of MC: Binary sensor for<br/>cmqttd status
    
    HA->>MQTT: Subscribe to Configs
    MQTT-->>HA: Device Discovered
    HA->>HA: Create Entities
```

## Error Handling and Recovery

### Retry Mechanism Flow

```mermaid
flowchart TD
    A[Command to Send] --> B[Acquire Confirmation Code]
    B --> C{Code Available?}
    
    C -->|No| D[Wait for Code]
    C -->|Yes| E[Send Packet]
    
    D --> B
    
    E --> F[Store in Pending]
    F --> G[Start Timer]
    
    G --> H{Response?}
    H -->|Yes| I[Success]
    H -->|No| J{Timeout?}
    
    J -->|No| H
    J -->|Yes| K{Retry Count?}
    
    K -->|< Max| L[Increment Count]
    K -->|>= Max| M[Give Up]
    
    L --> N[Wait Retry Interval]
    N --> O[Resend Packet]
    O --> G
    
    I --> P[Remove from Pending]
    M --> P
    P --> Q[Release Code]
    Q --> R[Complete]
```

### Memory Leak Prevention

```mermaid
flowchart TD
    A[Resource Allocation] --> B[Track Reference]
    
    B --> C{Event Type?}
    
    C -->|Normal Operation| D[Process Event]
    C -->|Connection Lost| E[Cleanup Triggered]
    C -->|Shutdown| F[Graceful Shutdown]
    
    D --> G{Resource Still Needed?}
    G -->|Yes| H[Keep Reference]
    G -->|No| I[Release Reference]
    
    E --> J[Force Cleanup]
    F --> J
    
    J --> K[Clear All Dictionaries]
    J --> L[Cancel All Tasks]
    J --> M[Close All Connections]
    
    K --> N[GC Collect]
    L --> N
    M --> N
    
    H --> C
    I --> C
    N --> O[Resources Freed]
```

## Integration Flows

### Docker Container Lifecycle

```mermaid
flowchart TD
    A[Docker Start] --> B[Load Environment]
    B --> C[Parse ENV Variables]
    
    C --> D{Config Valid?}
    D -->|No| E[Exit with Error]
    D -->|Yes| F[Start cmqttd]
    
    F --> G[Initialize Logging]
    G --> H[Load CBZ File]
    
    H --> I{CBZ Valid?}
    I -->|No| J[Use Default Labels]
    I -->|Yes| K[Extract Labels]
    
    J --> L[Connect to PCI]
    K --> L
    
    L --> M{Connection OK?}
    M -->|No| N[Retry Connection]
    M -->|Yes| O[Connect to MQTT]
    
    N --> P{Max Retries?}
    P -->|No| L
    P -->|Yes| E
    
    O --> Q[Start Event Loop]
    Q --> R[Running]
    
    R --> S{Signal Received?}
    S -->|SIGTERM| T[Graceful Shutdown]
    S -->|SIGINT| T
    S -->|No| R
    
    T --> U[Disconnect MQTT]
    U --> V[Disconnect PCI]
    V --> W[Cleanup Resources]
    W --> X[Exit Success]
```

### Home Assistant Integration

```mermaid
sequenceDiagram
    participant User
    participant HA as Home Assistant
    participant MQTT as MQTT Broker
    participant cmqttd
    participant CBus as C-Bus Network
    
    User->>HA: Toggle Light
    HA->>HA: Check Entity State
    HA->>MQTT: Publish Command
    
    MQTT->>cmqttd: Deliver Message
    cmqttd->>cmqttd: Process Command
    cmqttd->>CBus: Send C-Bus Command
    
    CBus-->>CBus: Execute Command
    CBus-->>cmqttd: Broadcast Change
    
    cmqttd->>cmqttd: Process Event
    cmqttd->>MQTT: Publish State
    
    MQTT->>HA: State Update
    HA->>HA: Update Entity
    HA->>User: Show New State
    
    Note over User,CBus: Total latency typically < 200ms
```

### Periodic Synchronization

```mermaid
flowchart TD
    A[Timer Elapsed] --> B[Check Sync Enabled]
    B --> C{Enabled?}
    
    C -->|No| D[Skip Sync]
    C -->|Yes| E[Log Sync Start]
    
    E --> F[Count Active Groups]
    F --> G[For Each Application]
    
    G --> H[Queue Status Requests]
    H --> I[Throttle Requests]
    
    I --> J[Send Request Block]
    J --> K[Process Responses]
    
    K --> L{State Changed?}
    L -->|Yes| M[Update MQTT]
    L -->|No| N[Skip Update]
    
    M --> O{More Blocks?}
    N --> O
    
    O -->|Yes| I
    O -->|No| P{More Apps?}
    
    P -->|Yes| G
    P -->|No| Q[Log Sync Complete]
    
    Q --> R[Reset Timer]
    R --> S[Wait Next Interval]
    
    D --> S
``` 