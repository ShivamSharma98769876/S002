# Development Tasks & Sub-tasks

This directory contains all development tasks and sub-tasks for the Automated Risk Management System for Zerodha Options Trading.

## Structure

- **tasks_index.json**: Master index file listing all 15 tasks with their dependencies and phases
- **task_XX_*.json**: Individual task files, each containing:
  - Task metadata (ID, name, description, priority, estimated hours, dependencies)
  - Sub-tasks with detailed acceptance criteria

## Task Overview

### Phase 1: Core Risk Monitoring
- **TASK-01**: System Architecture & Project Setup
- **TASK-02**: Zerodha Kite Connect API Integration
- **TASK-03**: Daily Loss Protection System
- **TASK-07**: Data Tracking & Storage

### Phase 2: Trailing SL Implementation
- **TASK-04**: Trailing Stop Loss Implementation

### Phase 3: Cycle-wise Profit Protection
- **TASK-05**: Cycle-wise Profit Protection

### Phase 4: Dashboard & Notifications
- **TASK-08**: Dashboard UI Development
- **TASK-09**: Notification System

### Phase 5: Security & Access Controls
- **TASK-12**: System Lock & Security (Admin Controls)

### Phase 6: Testing & Deployment
- **TASK-13**: Edge Cases Handling
- **TASK-14**: Testing & Quality Assurance
- **TASK-15**: Deployment & Maintenance

### Additional Tasks
- **TASK-06**: Real-time Monitoring & WebSocket
- **TASK-10**: Quantity Management
- **TASK-11**: Manual Override & User Controls

## Total Estimated Hours: 314 hours

## Usage

Each task JSON file follows this structure:
```json
{
  "task_id": "TASK-XX",
  "task_name": "Task Name",
  "description": "Task description",
  "priority": "High/Medium/Critical",
  "estimated_hours": 16,
  "dependencies": ["TASK-XX"],
  "sub_tasks": [
    {
      "sub_task_id": "TASK-XX-YY",
      "sub_task_name": "Sub-task Name",
      "description": "Sub-task description",
      "status": "pending",
      "estimated_hours": 4,
      "acceptance_criteria": [...]
    }
  ]
}
```

## Status Tracking

Each sub-task has a status field that can be:
- `pending`: Not yet started
- `in_progress`: Currently being worked on
- `completed`: Finished
- `blocked`: Blocked by dependencies or issues

