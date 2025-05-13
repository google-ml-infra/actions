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

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/bradleyfalzon/ghinstallation/v2"
	"github.com/google/go-github/v52/github"
	"golang.org/x/oauth2"
)

const (
	defaultBranch      = "main"
	maxRunsPerWorkflow = 20
	dataFile           = "workflow_runs.json"
	daysToConsider     = 14
	channelLimiting    = 10
)

// WorkFlowRun
type WorkflowRun struct {
	Run  *github.WorkflowRun            `json:"run"`
	Jobs map[string]*github.WorkflowJob `json:"jobs"`
}

// WorkflowRunData represents the combined data for a workflow run.
type WorkflowRunData struct {
	WorkflowID    int64          `json:"workflow_id"`
	WorkflowName  string         `json:"workflow_name"`
	WorkflowURL   string         `json:"workflow_url"`
	Runs          []*WorkflowRun `json:"runs"`
	LastUpdatedAt time.Time      `json:"last_updated_at"`
}

// GitHubAppConfig contains data needed to authenticate with a Github App Installation.
type GitHubAppConfig struct {
	GithubAppID             int64
	GithubAppInstallationID int64
	GithubAppPrivateKey     string
}

// Var to track the total requests for debugging purposes in relation to Github API limitations
var totalRequests int = 0

// Our deepest query can go way too fast for github api, we limit number of simletainous queries for job data
var limiterChannel = make(chan int, channelLimiting)

func main() {
	// 1. Read configuration from environment variables.
	repoOwner, repoName, targetBranch := readRepoConfig()

	// 2. Create a Github client.
	ctx := context.Background()
	client, err := getGithubClient(ctx)
	if err != nil {
		log.Fatalf("Failed to construct GitHub Client %v", err)
	}

	log.Printf("Getting data for Org:%s Repo:%s\n", repoOwner, repoName)

	// 3. Load previous data from file, if it exists.
	// previousData := loadPreviousData()

	// 4. Get all workflows for the repository.
	workflows, err := getWorkflows(ctx, client, repoOwner, repoName)
	if err != nil {
		log.Fatalf("Error getting workflows: %v", err)
	}

	// 5. Retrieve the latest runs for each workflow, on the specified branch.
	newData := make(map[int64]*WorkflowRunData)
	var wg sync.WaitGroup
	for _, workflow := range workflows {
		wg.Add(1)
		go func(workflow *github.Workflow) {
			defer wg.Done()
			runs, err := getWorkflowRuns(ctx, client, repoOwner, repoName, workflow.GetID(), targetBranch)
			if err != nil {
				log.Printf("Error getting runs for workflow %s (ID: %d): %v", workflow.GetName(), workflow.GetID(), err)
				return
			}

			newData[workflow.GetID()] = &WorkflowRunData{
				WorkflowID:    workflow.GetID(),
				WorkflowName:  workflow.GetName(),
				WorkflowURL:   workflow.GetHTMLURL(),
				Runs:          runs,
				LastUpdatedAt: time.Now(),
			}
		}(workflow)
	}
	wg.Wait()

	// 6. Merge new data with previous data.
	// mergedData := mergeData(previousData, newData)

	// 7. Store the merged data in a JSON file.
	// err = saveData(mergedData)
	err = saveData(newData)
	if err != nil {
		log.Fatalf("Error saving data: %v", err)
	}
	fmt.Printf("Number of api requestse made %d\n", totalRequests)

	fmt.Println("Workflow run data successfully gathered and stored.")
}

// Creates a Github client that is authenticated either with Github Token
// or Github App.
func getGithubClient(ctx context.Context) (*github.Client, error) {
	if githubToken, ok := os.LookupEnv("GH_TOKEN"); ok {
		fmt.Println("Using GitHub Token to authenticate")
		ts := oauth2.StaticTokenSource(
			&oauth2.Token{AccessToken: githubToken},
		)
		tc := oauth2.NewClient(ctx, ts)
		return github.NewClient(tc), nil
	}

	fmt.Println("Using GitHub App to authenticate")
	githubAppConfig, err := readGithubAppConfig()
	if err != nil {
		return nil, err
	}

	log.Printf("Github App ID %v installation ID %v", githubAppConfig.GithubAppID, githubAppConfig.GithubAppInstallationID)
	// Wrap the shared transport for use with the app ID authenticating with installation ID.
	itr, err := ghinstallation.New(http.DefaultTransport, githubAppConfig.GithubAppID, githubAppConfig.GithubAppInstallationID, []byte(githubAppConfig.GithubAppPrivateKey))

	if err != nil {
		return nil, err
	}

	// Use installation transport with client.
	return github.NewClient(&http.Client{Transport: itr}), nil
}

// readConfig reads configuration for the repository from environment variables.
func readRepoConfig() (string, string, string) {
	repoOwner := os.Getenv("GITHUB_REPOSITORY_ORG")
	repoName := os.Getenv("GITHUB_REPOSITORY_NAME")
	targetBranch := os.Getenv("TARGET_BRANCH")

	if repoOwner == "" {
		log.Fatal("Missing required environment variables: GITHUB_REPOSITORY_ORG")
	}

	if repoName == "" {
		log.Fatal("Missing required environment variables: GITHUB_REPOSITORY_NAME")
	}

	if targetBranch == "" {
		targetBranch = defaultBranch
		log.Printf("TARGET_BRANCH not set, using default: %s", defaultBranch)
	}

	return repoOwner, repoName, targetBranch
}

// Reads configuration from environment variables for authenticating using
// Github App.
func readGithubAppConfig() (GitHubAppConfig, error) {
	githubAppId, err := getIntEnvironmentVariable("GITHUB_APP_ID")
	if err != nil {
		return GitHubAppConfig{}, err
	}

	githubAppInstallationId, err := getIntEnvironmentVariable("GITHUB_APP_INSTALLATION_ID")
	if err != nil {
		return GitHubAppConfig{}, err
	}

	githubAppPrivateKey := os.Getenv("GITHUB_APP_PRIVATE_KEY")
	if githubAppPrivateKey == "" {
		return GitHubAppConfig{}, fmt.Errorf("missing required environment variables: GITHUB_APP_PRIVATE_KEY")
	}

	return GitHubAppConfig{githubAppId, githubAppInstallationId, githubAppPrivateKey}, nil
}

func getIntEnvironmentVariable(envName string) (int64, error) {
	rawValue, ok := os.LookupEnv(envName)
	if !ok {
		return 0, fmt.Errorf("missing environment variable: %v", envName)
	}

	intValue, err := strconv.ParseInt(rawValue, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("failed to convert %v with error: %v", envName, err)
	}
	return intValue, nil
}

// getWorkflows retrieves all workflows for a repository.
func getWorkflows(ctx context.Context, client *github.Client, owner, repo string) ([]*github.Workflow, error) {
	opts := &github.ListOptions{PerPage: 100}
	var allWorkflows []*github.Workflow
	for {
		workflows, resp, err := client.Actions.ListWorkflows(ctx, owner, repo, opts)
		if err != nil {
			return nil, err
		}
		totalRequests += 1
		allWorkflows = append(allWorkflows, workflows.Workflows...)
		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
	}
	return allWorkflows, nil
}

// getWorkflowRuns retrieves the latest runs for a specific workflow on a given branch.
func getWorkflowRuns(ctx context.Context, client *github.Client, owner, repo string, workflowID int64, branch string) ([]*WorkflowRun, error) {
	dateCreatedTerm := time.Now().AddDate(0, 0, -daysToConsider)
	optsCreated := dateCreatedTerm.Format(">2006-01-02")
	log.Printf("Date opts: %s\n", optsCreated)
	opts := &github.ListWorkflowRunsOptions{
		Branch:              branch,
		ListOptions:         github.ListOptions{PerPage: maxRunsPerWorkflow},
		ExcludePullRequests: true,
		Created:             optsCreated,
	}
	var allRuns []*WorkflowRun
	for {
		runs, resp, err := client.Actions.ListWorkflowRunsByID(ctx, owner, repo, workflowID, opts)
		if err != nil {
			return nil, err
		}
		totalRequests += 1
		for _, run := range runs.WorkflowRuns {
			// Nil out data we don't need that greatly bloats the size of the data
			run.Repository = nil
			run.HeadRepository = nil
			run.Actor = nil

			// Nil out author data so we don't hold names and emails in this json
			if run.HeadCommit != nil {
				run.HeadCommit.Author = nil
			}

			allRuns = append(allRuns, &WorkflowRun{Run: run, Jobs: map[string]*github.WorkflowJob{}})
		}
		if len(allRuns) >= maxRunsPerWorkflow {
			break
		}
		if resp.NextPage == 0 {
			break
		}
		opts.Page = resp.NextPage
		if len(allRuns) >= maxRunsPerWorkflow {
			break
		}
	}

	// Remove any extras, we are already hitting the api hard
	if len(allRuns) >= maxRunsPerWorkflow {
		allRuns = allRuns[:maxRunsPerWorkflow]
	}

	// Grab the WorkFlowJob data for each run
	var wg2 sync.WaitGroup
	for i, run := range allRuns {
		wg2.Add(1)
		limiterChannel <- 1

		go func(i int, run *WorkflowRun) {
			defer func() {
				wg2.Done()
				<-limiterChannel
			}()
			// we ingore resp, we are not pulling more than 100 jobs, that really shouldn't be happening and if it is we arn't going to be able to visulize that anyway.
			jobs, _, err := client.Actions.ListWorkflowJobs(ctx, owner, repo, run.Run.GetID(), &github.ListWorkflowJobsOptions{Filter: "latest", ListOptions: github.ListOptions{PerPage: 100}})
			if err != nil {
				log.Printf("Error getting jobs for run %d (ID: %d): %v", i, run.Run.GetID(), err)
				return
			}
			for _, job := range jobs.Jobs {
				// Remote the steps, while this data could be useful at some point we do not currently visuilizae and its quite large.
				// A user would find step level data by following the link to the job itself
				job.Steps = nil

				// Check if allRuns already contains this job name, if so we only release it if the RunAttempt is larger
				if _, ok := run.Jobs[*job.Name]; ok {
					if run.Jobs[*job.Name].GetRunAttempt() < job.GetRunAttempt() {
						run.Jobs[*job.Name] = job
					}
				} else {
					allRuns[i].Jobs[*job.Name] = job
				}
			}
			totalRequests += 1
		}(i, run)
	}
	wg2.Wait()

	return allRuns, nil
}

// loadPreviousData loads workflow run data from a file.
func loadPreviousData() map[int64]*WorkflowRunData {
	data, err := ioutil.ReadFile(dataFile)
	if err != nil {
		if os.IsNotExist(err) {
			log.Println("No previous data file found.")
		} else {
			log.Printf("Error reading previous data file: %v", err)
		}
		return make(map[int64]*WorkflowRunData)
	}

	var previousData map[int64]*WorkflowRunData
	err = json.Unmarshal(data, &previousData)
	if err != nil {
		log.Printf("Error unmarshalling previous data: %v", err)
		return make(map[int64]*WorkflowRunData)
	}

	return previousData
}

// // mergeData merges new workflow run data with previous data.
// func mergeData(previous, new map[int64]*WorkflowRunData) map[int64]*WorkflowRunData {
// 	merged := make(map[int64]*WorkflowRunData)

// 	// Add new data, overwriting old data if necessary
// 	for k, v := range new {
// 		merged[k] = v
// 	}

// 	// Add old data only if not present in the new data or if the new data is older
// 	for k, v := range previous {
// 		if _, ok := new[k]; !ok {
// 			merged[k] = v
// 		} else if new[k].LastUpdatedAt.Before(v.LastUpdatedAt) {
// 			// Take new runs, and append old runs to the end, up to the max
// 			combinedRuns := append([]*github.WorkflowRun{}, new[k].Runs...)
// 			for _, oldRun := range v.Runs {
// 				found := false
// 				for _, newRun := range new[k].Runs {
// 					if oldRun.GetID() == newRun.GetID() {
// 						found = true
// 						break
// 					}
// 				}
// 				if !found {
// 					combinedRuns = append(combinedRuns, oldRun)
// 				}
// 				if len(combinedRuns) >= maxRunsPerWorkflow {
// 					break
// 				}
// 			}
// 			if len(combinedRuns) > maxRunsPerWorkflow {
// 				combinedRuns = combinedRuns[:maxRunsPerWorkflow]
// 			}

// 			merged[k].Runs = combinedRuns
// 		}
// 	}

// 	return merged
// }

// saveData saves workflow run data to a JSON file.
func saveData(data map[int64]*WorkflowRunData) error {
	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}

	return ioutil.WriteFile(dataFile, jsonData, 0644)
}
