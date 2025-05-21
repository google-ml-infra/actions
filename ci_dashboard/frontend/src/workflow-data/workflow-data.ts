// Copyright 2025 Google LLC

// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//     https://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

export interface StatusInfo {
    name: string;
    url: string;
    status: string;
    icon: string;
    isTitle: boolean;
    isEmpty: boolean;
    date: string;
}

export interface HeadCommit {
    message: string;
    id: string;
    tree_id: string;
    timestamp: string;
}

export interface Run {
    id: number;
    name: string;
    node_id: string;
    head_branch: string;
    head_sha: string;
    run_number: number;
    run_attempt: number;
    event: string;
    status: string;
    conclusion: string;
    workflow_id: number;
    check_suite_id: number;
    check_suite_node_id: string;
    url: string;
    html_url: string;
    created_at: string;
    updated_at: string;
    run_started_at: string;
    jobs_url: string;
    logs_url: string;
    check_suite_url: string;
    artifacts_url: string;
    cancel_url: string;
    rerun_url: string;
    head_commit: HeadCommit;
    workflow_url: string;
}

export interface Job {
    id: number;
    run_id: number;
    run_url: string;
    node_id: string;
    head_branch: string;
    head_sha: string;
    url: string;
    html_url: string;
    status: string;
    conclusion: string;
    created_at: string;
    started_at: string;
    completed_at: string;
    name: string;
    check_run_url: string;
    labels: string[];
    runner_id: number;
    runner_name: string;
    runner_group_id: number;
    runner_group_name: string;
    run_attempt: number;
    workflow_name: string;
}

export interface WorkflowRunToJob {
    [name: string]: Job
}

export interface WorkflowRunData {
    run: Run;
    jobs: WorkflowRunToJob;
    showJobDetails: boolean;
}

export interface WorkflowData {
    workflow_id: number;
    workflow_name: string;
    workflow_url: string;
    runs: WorkflowRunData[] | null;
    last_updated_at: string;
    statusInfo: StatusInfo[] | null;
    expanded: boolean | null;
}


export interface WorkflowRuns {
    [workflowId: string]: WorkflowData;
}

export interface WorkflowBundle {
    dateRetreived: number;
    keyWorkflowJobs: WorkflowData[];
    otherWorkflowJobs: WorkflowData[];
}