# C-Bus Library - System Overview Diagrams

## Complete System Architecture

```mermaid
graph TB
    subgraph "Physical Layer"
        subgraph "C-Bus Network"
            SW[Wall Switches]
            DIM[Dimmers]
            SENS[Sensors]
            REL[Relays]
            TSTAT[Thermostats]
        end
        
        subgraph "C-Bus Wiring"
            PINK[Pink Wire - Data]
            BLUE[Blue Wire - Power]
        end
    end
    
    subgraph "Interface Layer"
        subgraph "PCI Hardware"
            SER[5500PC Serial PCI]
            USB[5500PCU USB PCI]
            ETH[5500CN Ethernet PCI]
        end
    end
    
    subgraph "libcbus Core"
        subgraph "Transport"
            SERIAL[Serial Connection]
            TCP[TCP Connection]
        end
        
        subgraph "Protocol Implementation"
            BUFF[Buffer Manager]
            DEC[Packet Decoder]
            ENC[Packet Encoder]
            CONF[Confirmation Manager]
        end
        
        subgraph "Packet Types"
            PM[Point-to-Multipoint]
            PP[Point-to-Point]
            DM[Device Management]
            ERR[Error Packets]
        end
        
        subgraph "Applications"
            LIGHT[Lighting App<br/>0x30-0x5F]
            CLOCK[Clock App<br/>0xDF]
            TEMP[Temperature App<br/>0x19]
            STATUS[Status App<br/>0xFF]
        end
    end
    
    subgraph "Integration Layer"
        subgraph "cmqttd Daemon"
            CBUSH[CBusHandler]
            MQTTC[MqttClient]
            DISC[Discovery Manager]
            SYNC[State Synchronizer]
        end
        
        subgraph "MQTT Topics"
            CMD[Command Topics<br/>/set]
            STATE[State Topics<br/>/state]
            CONFIG[Config Topics<br/>/config]
        end
    end
    
    subgraph "Home Automation"
        BROKER[MQTT Broker]
        HA[Home Assistant]
        DASH[Dashboard]
        AUTO[Automations]
    end
    
    %% Physical connections
    SW -.->|C-Bus Protocol| PINK
    DIM -.->|C-Bus Protocol| PINK
    SENS -.->|C-Bus Protocol| PINK
    REL -.->|C-Bus Protocol| PINK
    TSTAT -.->|C-Bus Protocol| PINK
    
    PINK --> SER
    PINK --> USB
    PINK --> ETH
    
    %% Data flow
    SER --> SERIAL
    USB --> SERIAL
    ETH --> TCP
    
    SERIAL --> BUFF
    TCP --> BUFF
    
    BUFF --> DEC
    DEC --> PM
    DEC --> PP
    DEC --> DM
    DEC --> ERR
    
    PM --> LIGHT
    PM --> CLOCK
    PM --> TEMP
    PP --> STATUS
    
    LIGHT --> CBUSH
    CLOCK --> CBUSH
    TEMP --> CBUSH
    STATUS --> CBUSH
    
    CBUSH <--> MQTTC
    MQTTC --> DISC
    MQTTC --> SYNC
    
    MQTTC <--> CMD
    MQTTC <--> STATE
    MQTTC --> CONFIG
    
    CMD <--> BROKER
    STATE <--> BROKER
    CONFIG --> BROKER
    
    BROKER <--> HA
    HA --> DASH
    HA --> AUTO
    
    %% Reverse flow for commands
    DASH --> HA
    AUTO --> HA
    HA --> BROKER
    BROKER --> CMD
    CMD --> MQTTC
    MQTTC --> CBUSH
    CBUSH --> ENC
    ENC --> CONF
    CONF --> SERIAL
    CONF --> TCP
    
    style SW fill:#e1f5fe
    style DIM fill:#e1f5fe
    style SENS fill:#e1f5fe
    style REL fill:#e1f5fe
    style TSTAT fill:#e1f5fe
    
    style SER fill:#fff3e0
    style USB fill:#fff3e0
    style ETH fill:#fff3e0
    
    style LIGHT fill:#e8f5e9
    style CLOCK fill:#e8f5e9
    style TEMP fill:#e8f5e9
    style STATUS fill:#e8f5e9
    
    style HA fill:#fce4ec
    style BROKER fill:#f3e5f5
```

## Data Flow Overview

```mermaid
sequenceDiagram
    participant User
    participant HA as Home Assistant
    participant MQTT as MQTT Broker
    participant cmqttd
    participant libcbus as libcbus Protocol
    participant PCI as PCI Hardware
    participant CBus as C-Bus Device
    
    Note over User,CBus: Bi-directional communication flow
    
    rect rgb(200, 230, 201)
        Note left of User: User Action Flow
        User->>HA: Toggle Light
        HA->>MQTT: Publish to /set topic
        MQTT->>cmqttd: Deliver command
        cmqttd->>libcbus: Convert to C-Bus command
        libcbus->>PCI: Send encoded packet
        PCI->>CBus: Execute command
    end
    
    rect rgb(255, 224, 178)
        Note right of CBus: Device Event Flow
        CBus->>PCI: Status change
        PCI->>libcbus: Raw packet data
        libcbus->>cmqttd: Decoded event
        cmqttd->>MQTT: Publish to /state topic
        MQTT->>HA: Update entity state
        HA->>User: Display new state
    end
    
    rect rgb(225, 190, 231)
        Note over cmqttd,libcbus: Periodic Sync
        loop Every 300 seconds
            cmqttd->>libcbus: Request all status
            libcbus->>PCI: Status queries
            PCI->>CBus: Get states
            CBus-->>PCI: Current states
            PCI-->>libcbus: Status reports
            libcbus-->>cmqttd: Process reports
            cmqttd->>MQTT: Update all states
        end
    end
```

## Component Interaction Matrix

```mermaid
graph LR
    subgraph "Component Dependencies"
        subgraph "Core Components"
            PCI_PROTO[PCIProtocol]
            PKT_MGR[Packet Manager]
            CONF_MGR[Confirmation Manager]
            EVT_DISP[Event Dispatcher]
        end
        
        subgraph "Application Handlers"
            LIGHT_HDL[Lighting Handler]
            CLOCK_HDL[Clock Handler]
            TEMP_HDL[Temperature Handler]
            STAT_HDL[Status Handler]
        end
        
        subgraph "Integration Components"
            CBUS_HDL[CBusHandler]
            MQTT_CLI[MqttClient]
            DISC_MGR[Discovery Manager]
            STATE_MGR[State Manager]
        end
    end
    
    %% Core dependencies
    PCI_PROTO --> PKT_MGR
    PCI_PROTO --> CONF_MGR
    PKT_MGR --> EVT_DISP
    
    %% Application dependencies
    EVT_DISP --> LIGHT_HDL
    EVT_DISP --> CLOCK_HDL
    EVT_DISP --> TEMP_HDL
    EVT_DISP --> STAT_HDL
    
    %% Integration dependencies
    LIGHT_HDL --> CBUS_HDL
    CLOCK_HDL --> CBUS_HDL
    TEMP_HDL --> CBUS_HDL
    STAT_HDL --> CBUS_HDL
    
    CBUS_HDL --> MQTT_CLI
    MQTT_CLI --> DISC_MGR
    MQTT_CLI --> STATE_MGR
    
    %% Reverse dependencies
    MQTT_CLI -.-> CBUS_HDL
    CBUS_HDL -.-> PCI_PROTO
    
    style PCI_PROTO fill:#b3e5fc
    style CBUS_HDL fill:#c5e1a5
    style MQTT_CLI fill:#ffccbc
```

## State Management

```mermaid
stateDiagram-v2
    [*] --> Initializing
    
    Initializing --> Connecting: Start Application
    
    Connecting --> Connected: Connection Success
    Connecting --> Error: Connection Failed
    
    Connected --> Resetting: Send Reset
    
    Resetting --> Ready: Reset Complete
    Resetting --> Error: Reset Failed
    
    Ready --> Processing: Normal Operation
    
    Processing --> Processing: Handle Events
    Processing --> Syncing: Periodic Sync
    Processing --> Error: Protocol Error
    
    Syncing --> Processing: Sync Complete
    Syncing --> Error: Sync Failed
    
    Error --> Reconnecting: Auto Retry
    Error --> [*]: Fatal Error
    
    Reconnecting --> Connecting: Retry Connection
    Reconnecting --> [*]: Max Retries
    
    note right of Ready
        System fully operational:
        - Process commands
        - Handle events
        - Maintain sync
    end note
    
    note right of Syncing
        Periodic tasks:
        - Status updates
        - Clock sync
        - State verification
    end note
    
    note right of Error
        Error recovery:
        - Clean resources
        - Log details
        - Attempt recovery
    end note
```

## Memory and Resource Management

```mermaid
flowchart TD
    subgraph "Resource Lifecycle"
        subgraph "Allocation"
            A1[Connection Created]
            A2[Buffers Allocated]
            A3[Tasks Started]
            A4[Handlers Registered]
        end
        
        subgraph "Operation"
            O1[Process Packets]
            O2[Handle Events]
            O3[Manage Confirmations]
            O4[Update States]
        end
        
        subgraph "Cleanup"
            C1[Connection Lost]
            C2[Cancel Tasks]
            C3[Clear Buffers]
            C4[Release Codes]
            C5[Clear References]
        end
    end
    
    A1 --> A2
    A2 --> A3
    A3 --> A4
    A4 --> O1
    
    O1 --> O2
    O2 --> O3
    O3 --> O4
    O4 --> O1
    
    O1 --> C1
    O2 --> C1
    O3 --> C1
    O4 --> C1
    
    C1 --> C2
    C2 --> C3
    C3 --> C4
    C4 --> C5
    C5 --> A1
    
    style A1 fill:#c8e6c9
    style C1 fill:#ffcdd2
    style C5 fill:#ffecb3
```

## Performance Metrics

```mermaid
graph LR
    subgraph "Performance Characteristics"
        subgraph "Latency"
            L1[Command Send: ~10ms]
            L2[PCI Process: ~20ms]
            L3[C-Bus Execute: ~50ms]
            L4[Event Return: ~20ms]
            L5[MQTT Publish: ~10ms]
            L6[Total: <200ms]
        end
        
        subgraph "Throughput"
            T1[Commands: 10/sec]
            T2[Events: 100/sec]
            T3[Status: 32 groups/req]
            T4[Sync: Every 300s]
        end
        
        subgraph "Resources"
            R1[Memory: ~50MB]
            R2[CPU: <5% idle]
            R3[Network: <10KB/s]
            R4[Connections: 2-3]
        end
    end
    
    L1 --> L2
    L2 --> L3
    L3 --> L4
    L4 --> L5
    L5 --> L6
    
    style L6 fill:#a5d6a7,stroke:#4caf50,stroke-width:3px
    style T1 fill:#90caf9,stroke:#2196f3,stroke-width:3px
    style R1 fill:#ffcc80,stroke:#ff9800,stroke-width:3px
``` 