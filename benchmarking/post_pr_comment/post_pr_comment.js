// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * Posts or updates A/B benchmark reports on PRs using a "sticky" comment to avoid clutter.
 * It also appends the current run to a persistent history log within the comment for audit tracking.
 *
 * This script assumes that the GITHUB_WORKSPACE environment variable is set (standard in GitHub runners)
 * and that the ab_report.md file exists at the root of the GITHUB_WORKSPACE.
 */

const fs = require('fs');
const path = require('path');

module.exports = async ({ github, context }) => {
  // Read Report
  const reportPath = path.join(process.env.GITHUB_WORKSPACE, 'ab_report.md');
  let reportContent = '';
  
  try {
    if (fs.existsSync(reportPath)) {
      reportContent = fs.readFileSync(reportPath, 'utf8');
    } else {
      console.log(`Report file not found at: ${reportPath}`);
      reportContent = "_A/B report file not found._";
    }
  } catch (error) {
    console.error("Error reading report: " + error);
    reportContent = "_Error reading A/B report content._";
  }

  const workflowName = context.workflow;

  // Define HTML comments.
  // MAIN_MARKER serves as a unique identifier for the comment.
  const MAIN_MARKER = '<!-- BAP: ' + workflowName + ' -->';
  const HISTORY_START = '<!-- HISTORY_LIST_START -->';
  const HISTORY_END = '<!-- HISTORY_LIST_END -->';

  // Prepare new run entry
  const runUrl = `https://github.com/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`;
  const timestamp = new Date().toISOString().substring(0, 19).replace('T', ' ') + ' UTC';
  const newRunEntry = `* [Run ${context.runId}](${runUrl}) - ${timestamp}`;

  // Find existing comment & extract history.
  const { data: comments } = await github.rest.issues.listComments({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: context.issue.number,
  });

  const existingComment = comments.find(c => c.body.includes(MAIN_MARKER));
  let previousRunsList = "";

  if (existingComment) {
    // Extract content between the history markers
    const historyRegex = new RegExp(`${HISTORY_START}([\\s\\S]*?)${HISTORY_END}`);
    const match = existingComment.body.match(historyRegex);
    if (match && match[1]) {
      previousRunsList = match[1].trim();
    }
  }

  // Build history block (new + old)
  const combinedHistory = `${HISTORY_START}\n${newRunEntry}\n${previousRunsList}\n${HISTORY_END}`;

  // Assemble full comment body
  const historySection = `
<details>
<summary><strong>Run History</strong></summary>

${combinedHistory}
</details>
`;

	const commentBody = `${MAIN_MARKER}\n**Last Updated:** ${timestamp}\n\n${reportContent}\n\n${historySection}`;
  // Update or create comment
  if (existingComment) {
    console.log(`Updating existing comment ${existingComment.id}.`);
    await github.rest.issues.updateComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      comment_id: existingComment.id,
      body: commentBody
    });
  } else {
    console.log("Creating new comment.");
    await github.rest.issues.createComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      issue_number: context.issue.number,
      body: commentBody
    });
  }
};
