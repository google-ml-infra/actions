import { Injectable, OnDestroy } from '@angular/core';
import { Observable, timer, Subscription, Subject } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { switchMap, tap, share, retry, takeUntil, map } from 'rxjs/operators';
import { WorkflowBundle, WorkflowData, StatusInfo } from './workflow-data';

@Injectable({
  providedIn: 'root'
})
export class WorkflowService implements OnDestroy {
  dataLocation = 'https://storage.googleapis.com/download/storage/v1/b/ml-dashboard-data-gatherer/o/workflow_runs.json?alt=media'
  keyWorkflowNames: string[] = [
    'CI',
    'CI - Cloud TPU (nightly)',
    'CoreQL', 'CI - Address Sanitizer (nightly)',
    'CI - Wheel Tests (Continuous)',
    'CI - Wheel Tests (Nightly/Release)',
    'CI - Bazel CPU tests (RBE)',
    'CI - Bazel CUDA tests (RBE)',
  ];

  private bundle$: Observable<WorkflowBundle>;
  private previousBundle: WorkflowBundle;

  private stopPolling = new Subject();

  constructor(private http: HttpClient) {

    this.previousBundle = {
      dateRetreived: 0,
      keyWorkflowJobs: [],
      otherWorkflowJobs: [],
    }
    // Pull data every 4 minutes, data refreshes every 10 minutes
    this.bundle$ = timer(1, 1000 * 60 * 4).pipe(
      switchMap(() => http.get(this.dataLocation).pipe(map(data => {
        console.log("Retreived new data")
        // TODO: Merge results at the top level to prevent flickering / opening and closing of the expanion panels
        let wb: WorkflowBundle = {
          dateRetreived: Date.now(),
          keyWorkflowJobs: [],
          otherWorkflowJobs: [],
        }
        Object.entries(data).map(([key, value]) => {

          // If there was previous data we need to persist the expanded state or the screen flickers
          let expanded = new Set<number>();
          this.previousBundle.keyWorkflowJobs.forEach(j => {
            if(j.expanded!){
              console.log("Workflow %s was already expanded",j.workflow_name)
              expanded.add(j.workflow_id)
            }
          });

          const workData = value as WorkflowData
          if (workData.runs != null) {
            let wd = value as WorkflowData; // Type assertion to Workflow
            wd.statusInfo = this.statusInfoForWorkflow(wd);
            if (expanded.has(wd.workflow_id)) {
              wd.expanded = true;
            } else {
              wd.expanded = false;
            }
            if (this.keyWorkflowNames.includes(wd.workflow_name)) {
              wb.keyWorkflowJobs.push(wd);
            } else {
              wb.otherWorkflowJobs.push(wd);
            }
          }
        });
        this.previousBundle = wb;
        return wb
      }))),
      retry(),
      tap(console.log),
      share(),
      takeUntil(this.stopPolling)
    );
  }


  getWorklowBundle(): Observable<WorkflowBundle> {
    return this.bundle$.pipe(
      tap(() => console.log('data sent to subscriber'))
    );
  }

  ngOnDestroy() {
    // this.stopPolling.next();
  }

  // Translate the github statuses to how we want to display them
  statusIconForJob(status: string, conclusion: string): string {

    if (status == "completed" && conclusion == "success") {
      return "check_circle"
    }
    if (status == "completed" && conclusion == "failure") {
      return "cancel"
    }
    if (status == "completed" && conclusion == "cancelled") {
      return "block"
    }
    if (status == "completed" && conclusion == "skipped") {
      return "skip_next"
    }
    if (status == "in_progress" || status == "running") {
      return "run_circle"
    }
    if (status == "queued" || status == "pending") {
      return "pending"
    }
    return "unknown_med"
  }

  // Used for css and alt-text
  statusForJob(status: string, conclusion: string): string {

    if (status == "completed" && conclusion == "success") {
      return "success"
    }
    if (status == "completed" && conclusion == "failure") {
      return "failure"
    }
    if (status == "completed" && conclusion == "cancelled") {
      return "cancelled"
    }
    if (status == "completed" && conclusion == "skipped") {
      return "skipped"
    }
    if (status == "in_progress") {
      return "running"
    }
    if (status == "queued" || status == "pending") {
      return "pending"
    }
    return "unknown"
  }

  toggleJobDetails(runData: any): void {
    runData.showJobDetails = !runData.showJobDetails;
  }

  titlesForWorkFlow(workData: WorkflowData): Array<string> {
    let names = Array<string>()
    names.push("Overall")
    if (workData.runs?.length == 0) {
      return names
    }
    const firstRun = workData.runs![0]
    const keys = Object.keys(firstRun.jobs).sort()
    names.push(...keys)
    return names
  }

  makeEmptyStatus(): StatusInfo {
    const jobStatus: StatusInfo = {
      name: "",
      url: "",
      status: "",
      icon: "",
      date: "",
      isTitle: false,
      isEmpty: true,
    }
    return jobStatus
  }

  // Flatten into how we structure columns
  statusInfoForWorkflow(workflowData: WorkflowData): Array<StatusInfo> {
    let statusInfo = Array<StatusInfo>()
    const numberPerRow = 11

    // Grab the names
    let names = Array<string>()

    // Populate the header which is the job level data, while we do that we will also figure out the names for the next rows
    const summary: StatusInfo = {
      name: "Overall",
      url: "", // TODO: we can gather this
      status: "",
      icon: "",
      date: "",
      isTitle: true,
      isEmpty: false,
    }
    statusInfo.push(summary)

    // We reuse this multiple times so pull it out now
    const firstRun = workflowData.runs![0]

    // Note: The api gatherer will omit any result that does not have at least a single run
    for (let i = 0; i < 10; i++) {
      // If there are not enough runs we will need to pad out
      if (workflowData.runs!.length <= i) {
        statusInfo.push(this.makeEmptyStatus())
        continue
      }
      const runData = workflowData.runs![i]
      if (runData == undefined) {
        console.log("Why did this happen")
      }
      // Lets figure out the naming order we expect for all subsequent rows
      if (i == 0) {
        names = Object.keys(runData.jobs).sort()
      }
      const jobStatus: StatusInfo = {
        name: runData.run.name,
        url: runData.run.html_url,
        date: runData.run.updated_at,
        status: this.statusForJob(runData.run.status, runData.run.conclusion),
        icon: this.statusIconForJob(runData.run.status, runData.run.conclusion),
        isTitle: false,
        isEmpty: false,
      }
      statusInfo.push(jobStatus)
    }

    // Now for each job name we will iterate
    names.forEach(name => {
      // Grab row 0 data by looking at the run from the first run
      const job = firstRun.jobs[name]
      const jobStatus: StatusInfo = {
        name: job.name,
        url: job.html_url,
        date: job.completed_at,
        status: "",
        icon: "",
        isTitle: true,
        isEmpty: false,
      }
      statusInfo.push(jobStatus)


      // Now iterate all 10 results
      for (let i = 0; i < 10; i++) {
        // If there are not enough runs we will need to pad out
        if (workflowData.runs!.length <= i) {
          statusInfo.push(this.makeEmptyStatus())
          continue
        }
        const runData = workflowData.runs![i]
        if (runData.run == undefined) {
          console.log("Why did this happen")
        }
        // If we pulled no job data that is typically from a renaming, we omit it here. 
        const jobData = runData.jobs[name]
        if (jobData == undefined) {
          statusInfo.push(this.makeEmptyStatus())
          continue
        }

        const jobStatus: StatusInfo = {
          name: "",
          date: jobData.created_at,
          url: jobData.html_url,
          status: this.statusForJob(jobData.status, jobData.conclusion),
          icon: this.statusIconForJob(jobData.status, jobData.conclusion),
          isTitle: false,
          isEmpty: false,
        }
        statusInfo.push(jobStatus)
      }

    });



    console.log("Attempting to calculate status infos for workflow %s", workflowData.workflow_name)
    return statusInfo
  }
}






